"""Preregister and run one immutable 50-stock hourly research round, VALID only."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, text

from helios.alpha.definition import AlphaDefinition
from helios.common.config import config_hash, load_config
from helios.common.db import get_engine
from helios.common.lineage import PROJECT_ROOT, git_commit, git_is_dirty
from helios.common.project_config import GatesConfig
from helios.data.equities import constituents, sha256, write_json
from helios.data.snapshots import Snapshot, SnapshotFile, compute_snapshot_id, register_snapshot
from helios.equities.config import EquityResearchPolicy
from helios.equities.inputs import load_equity_inputs
from helios.equities.model import EquityModel, fit_equity_model, model_protocol
from helios.registry.api import AlphaDefinition as RegistryDefinition
from helios.registry.api import register_definition
from helios.registry.experiments import (
    ExperimentKind,
    ExperimentStatus,
    register_experiment,
    set_status,
)
from helios.registry.gates import store_gate_config
from helios.registry.results import Split
from helios.sim.equity_evaluation import EquityEvaluationContext, equity_gates_path
from helios.sim.evaluate import evaluate

CANDIDATES = {
    "momentum": "clip(sign(return_1), 0, 1)",
    "reversal": "clip(-sign(return_1), 0, 1)",
    "ml": None,
}

REFERENCE_CANDIDATES: dict[str, str | None] = {
    "volume_shock": "clip(relative_volume_3 - 1, 0, 1)",
}

# Fixed before any new VALID P&L. Each is a distinct hypothesis, not a tuning grid.
EXTENDED_CANDIDATES: dict[str, str | None] = {
    "trend_3": "clip(sign(return_3), 0, 1)",
    "reversal_3": "clip(-sign(return_3), 0, 1)",
    "vol_scaled_trend": "clip(return_3 / (2 * volatility_3), 0, 1)",
    "body_reversal": "clip(-body / range, 0, 1)",
    "close_strength": "clip(2 * close_location - 1, 0, 1)",
    "close_fade": "clip(1 - 2 * close_location, 0, 1)",
    "volume_trend": "clip(sign(return_1) * relative_volume_3, 0, 1)",
    "gap_reversal": "clip(-sign(open_gap), 0, 1)",
}


def candidate_definition(
    round_id: str,
    candidate: str,
    model: EquityModel,
    *,
    policy: EquityResearchPolicy | None = None,
    candidates: dict[str, str | None] | None = None,
) -> RegistryDefinition:
    """Keep research metadata outside the DSL's numeric parameter namespace."""
    policy = EquityResearchPolicy() if policy is None else policy
    expression = (CANDIDATES if candidates is None else candidates)[candidate]
    definition = AlphaDefinition(
        alpha_id=f"{round_id}_{candidate}",
        version=1,
        name=f"NSE {policy.interval} {candidate} development benchmark",
        provenance="ML" if expression is None else "QUANT",
        feature_set_version=policy.feature_set_version,
        horizon_family="H-HOURLY" if policy.interval == "1h" else "H-MINUTE",
        horizon_periods=1,
        expression=expression,
        model_ref="sha256:" + model.model_hash if expression is None else None,
        params={},
        author="helios_equity_research",
    ).to_registry()
    return definition.model_copy(
        update={
            "spec": definition.spec
            | dict(
                market="nse_cash",
                research_round=round_id,
                model_sha256=model.model_hash,
                calibration_sha256=model.calibration_hash,
            )
        }
    )


def registry_fingerprint(engine: Engine) -> dict[str, Any]:
    """Only the existing non-equity research, plus the global TEST audit count."""
    answer = {}
    with engine.connect() as connection:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        for table in ("alpha_definitions", "alpha_results"):
            rows: list[Any] = list(
                connection.execute(
                    text(
                        f"SELECT to_jsonb(t) FROM {table} t WHERE alpha_id NOT LIKE 'nse_%' "
                        "ORDER BY to_jsonb(t)::text"
                    )
                )
                .scalars()
                .all()
            )
            answer[table] = dict(
                count=len(rows),
                sha256=hashlib.sha256(
                    json.dumps(rows, sort_keys=True, default=str).encode()
                ).hexdigest(),
            )
        answer["test_accesses"] = connection.execute(
            text("SELECT count(*) FROM test_set_access")
        ).scalar_one()
    return answer


def run_round(
    snapshot: Path,
    round_id: str,
    *,
    engine: Engine | None = None,
    interval: str = "1h",
    suite: str = "baseline",
    research_symbols: tuple[str, ...] = (),
    workers: int = 1,
    repaired: bool = False,
) -> Path:
    if not re.fullmatch(r"nse_[a-z0-9_]{3,32}", round_id):
        raise ValueError(
            "round ID must start nse_ and contain lowercase letters/digits/underscores"
        )
    if interval not in ("1h", "1m") or suite not in ("baseline", "reference", "extended", "all"):
        raise ValueError("unsupported equity interval/suite")
    if repaired and interval != "1m":
        raise ValueError("repaired public snapshots require minute frequency")
    policy = (
        EquityResearchPolicy(
            version="nse_minute_research_v2",
            interval="1m",
            session="reviewed_sessions_v2",
            commission_tax_proxy_bps=0,
        )
        if repaired
        else EquityResearchPolicy()
        if interval == "1h"
        else EquityResearchPolicy(version="nse_minute_research_v1", interval="1m")
    )
    if not 1 <= workers <= 4:
        raise ValueError("equity research permits one to four isolated execution workers")
    candidates = CANDIDATES.copy() if suite == "baseline" else EXTENDED_CANDIDATES.copy()
    if suite == "reference":
        candidates = REFERENCE_CANDIDATES.copy()
    if suite == "all":
        candidates = CANDIDATES | REFERENCE_CANDIDATES | EXTENDED_CANDIDATES
    engine = get_engine() if engine is None else engine
    output = PROJECT_ROOT / "reports_out/equity_research" / round_id
    output.mkdir(parents=True, exist_ok=False)
    (output / "source").mkdir()
    source_hashes = {}
    sources = list((PROJECT_ROOT / "research/helios").rglob("*.py")) + [
        equity_gates_path(policy),
        PROJECT_ROOT / "pyproject.toml",
        PROJECT_ROOT / "uv.lock",
    ]
    for source_file in sorted(sources):
        relative = source_file.relative_to(PROJECT_ROOT)
        target = output / "source" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_file, target)
        source_hashes[str(relative)] = sha256(target)
    before = registry_fingerprint(engine)
    write_json(output / "registry_before.json", before)
    protocol = dict(
        round_id=round_id,
        policy=policy.model_dump(mode="json"),
        candidates=candidates,
        model=model_protocol(policy),
        source_commit=git_commit(),
        dirty=git_is_dirty(),
        source_hashes=source_hashes,
        source_manifest_sha256=sha256(snapshot / "manifest.json"),
        source_snapshot=str(snapshot),
        test_access=False,
        automatic_promotion=False,
        scope=(
            "1m conditional historical-member research; screened observations only"
            if repaired
            else f"{interval} conditional intraday research; "
            "all frozen constituents in model inputs"
        ),
        research_symbols=research_symbols,
        execution_workers=workers,
        coverage="ex-post complete-session conditional study; excluded sessions stay unknown",
    )
    write_json(output / "protocol.json", protocol)
    if repaired:
        if interval != "1m":
            raise ValueError("repaired public snapshot currently supports minute research only")
        source_manifest = json.loads((snapshot / "manifest.json").read_text())
        symbols = [r["symbol"] for r in source_manifest["files"] if r["eligible_rows"] > 0]
    else:
        roster = constituents((snapshot / "constituents.csv").read_bytes())
        symbols = [row["Symbol"] for row in roster]
    inputs = [load_equity_inputs(snapshot, symbol, policy) for symbol in symbols]
    selected = tuple(item.symbol for item in inputs) if not research_symbols else research_symbols
    if len(set(selected)) != len(selected) or not set(selected) <= {item.symbol for item in inputs}:
        raise ValueError("research companies must be distinct frozen constituents")
    (output / "inputs").mkdir()
    files = []
    for item in inputs:
        path = output / "inputs" / f"{item.symbol}.parquet"
        item.bars.to_parquet(path, index=False)
        files.append(
            SnapshotFile(str(path.relative_to(PROJECT_ROOT)), sha256(path), path.stat().st_size)
        )
    snapshot_record = Snapshot(
        snapshot_id=compute_snapshot_id(files),
        source="yahoo_nse_research_prefix" if interval == "1h" else "upstox_nse_research_prefix",
        interval=policy.interval,
        symbols=[item.symbol for item in inputs],
        first_open_time=min(int(item.bars.open_time.min()) for item in inputs),
        last_open_time=max(int(item.bars.open_time.max()) for item in inputs),
        file_count=len(files),
        row_count=sum(len(item.bars) for item in inputs),
        total_bytes=sum(file.bytes for file in files),
        code_commit=git_commit(),
        files=files,
    )
    write_json(output / "snapshot.json", asdict(snapshot_record))
    gates = load_config(equity_gates_path(policy), GatesConfig)
    with engine.begin() as connection:
        register_snapshot(connection, snapshot_record)
        store_gate_config(connection, gates, author="helios_equity_research")
        ml_experiment = register_experiment(
            connection,
            hypothesis=(
                "Fixed hourly classifier with disjoint TRAIN-tail expected-return calibration"
            ),
            params=model_protocol(policy)
            | {"policy": policy.model_dump(mode="json"), "source_hashes": source_hashes},
            kind=ExperimentKind.ML,
            author="helios_equity_research",
            code_commit=git_commit(),
            config_hash=config_hash(policy),
            snapshot_id=snapshot_record.snapshot_id,
            notes="Development source archived; no VALID selection or TEST access.",
        )
        set_status(connection, ml_experiment.experiment_id, ExperimentStatus.RUNNING)
    model, calibration = fit_equity_model(inputs, policy, output / "ml")
    with engine.begin() as connection:
        set_status(connection, ml_experiment.experiment_id, ExperimentStatus.FINISHED)
    attempts: list[dict[str, Any]] = []
    with engine.begin() as connection:
        for candidate in candidates:
            identifier = f"{round_id}_{candidate}"
            register_definition(
                connection,
                candidate_definition(
                    round_id, candidate, model, policy=policy, candidates=candidates
                ),
            )
            for source in inputs:
                if source.symbol not in selected:
                    continue
                params: dict[str, Any] = dict(
                    market="nse_cash",
                    symbol=source.symbol,
                    alpha_id=identifier,
                    policy_hash=config_hash(policy),
                    model_hash=model.model_hash,
                    calibration_hash=model.calibration_hash,
                    source_hashes=source_hashes,
                )
                if workers != 1:
                    params["execution_workers"] = workers
                experiment = register_experiment(
                    connection,
                    hypothesis=(
                        f"{candidate} has positive net intraday edge on {source.symbol} "
                        "in frozen VALID"
                    ),
                    params=params,
                    kind=ExperimentKind.ALPHA,
                    author="helios_equity_research",
                    code_commit=git_commit(),
                    config_hash=config_hash(policy),
                    snapshot_id=snapshot_record.snapshot_id,
                    notes=(
                        "Conditional complete-session development benchmark; G7 blocks promotion."
                    ),
                )
                attempts.append(
                    dict(
                        candidate=candidate,
                        alpha_id=identifier,
                        symbol=source.symbol,
                        experiment_id=experiment.experiment_id,
                    )
                )
    write_json(output / "preregistration.json", dict(attempts=attempts, calibration=calibration))
    results = []
    by_symbol = {source.symbol: source for source in inputs}
    for index, attempt in enumerate(attempts, 1):
        with engine.begin() as connection:
            set_status(connection, attempt["experiment_id"], ExperimentStatus.RUNNING)
        result = evaluate(
            attempt["alpha_id"],
            Split.VALID,
            attempt["experiment_id"],
            engine=engine,
            output_dir=output / "evaluations",
            reported=False,
            equity=EquityEvaluationContext(
                policy,
                by_symbol[attempt["symbol"]],
                snapshot_record.snapshot_id,
                model,
                source_hashes,
                workers=workers,
            ),
        )
        with engine.begin() as connection:
            set_status(connection, attempt["experiment_id"], ExperimentStatus.FINISHED)
        assert result.evaluation_json is not None
        row = attempt | dict(
            run_id=result.run_id,
            status=result.status.value,
            sharpe=None if result.sharpe is None else float(result.sharpe),
            fitness=None if result.fitness is None else float(result.fitness),
            gates=result.gate_results,
            artifact=result.evaluation_json["artifact"],
            artifact_sha256=result.evaluation_json["artifact_sha256"],
        )
        results.append(row)
        with (output / "outcomes.jsonl").open("a") as handle:
            handle.write(json.dumps(row) + "\n")
        print(
            f"{index}/{len(attempts)} {attempt['candidate']} "
            f"{attempt['symbol']} {result.status.value}",
            flush=True,
        )
    for source_name, digest in source_hashes.items():
        if sha256(PROJECT_ROOT / source_name) != digest:
            raise ValueError("source changed during equity research; do not finalize the round")
    after = registry_fingerprint(engine)
    if before != after:
        raise ValueError("existing crypto research or TEST access changed during the equity round")
    summary = dict(
        round_id=round_id,
        market="nse_cash",
        snapshot_id=snapshot_record.snapshot_id,
        protocol_sha256=sha256(output / "protocol.json"),
        results=results,
        model_hash=model.model_hash,
        calibration_hash=model.calibration_hash,
        dirty=git_is_dirty(),
        source_commit=git_commit(),
        test_accesses=0,
        registry_before=before,
        registry_after=after,
        crypto_unchanged=True,
        promoted=0,
        scope=protocol["scope"],
        interval=policy.interval,
        research_symbols=selected,
        model_symbols=[source.symbol for source in inputs],
    )
    write_json(output / "summary.json", summary)
    print(f"Completed: {output / 'summary.json'}", flush=True)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--round-id", required=True)
    parser.add_argument("--interval", choices=("1h", "1m"), default="1h")
    parser.add_argument(
        "--suite", choices=("baseline", "reference", "extended", "all"), default="baseline"
    )
    parser.add_argument("--research-symbols", nargs="*", default=[])
    parser.add_argument("--workers", type=int, choices=(1, 2, 3, 4), default=1)
    parser.add_argument("--repaired", action="store_true")
    args = parser.parse_args()
    run_round(
        args.snapshot,
        args.round_id,
        interval=args.interval,
        suite=args.suite,
        research_symbols=tuple(args.research_symbols),
        workers=args.workers,
        repaired=args.repaired,
    )


if __name__ == "__main__":
    main()
