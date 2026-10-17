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
from helios.equities.model import MODEL_PROTOCOL, EquityModel, fit_equity_model
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
from helios.sim.equity_evaluation import GATES_PATH, EquityEvaluationContext
from helios.sim.evaluate import evaluate

CANDIDATES = {
    "momentum": "clip(sign(return_1), 0, 1)",
    "reversal": "clip(-sign(return_1), 0, 1)",
    "ml": None,
}


def candidate_definition(round_id: str, candidate: str, model: EquityModel) -> RegistryDefinition:
    """Keep research metadata outside the DSL's numeric parameter namespace."""
    expression = CANDIDATES[candidate]
    definition = AlphaDefinition(
        alpha_id=f"{round_id}_{candidate}",
        version=1,
        name=f"NSE hourly {candidate} development benchmark",
        provenance="ML" if expression is None else "QUANT",
        feature_set_version="nse_session_features_v1",
        horizon_family="H-HOURLY",
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


def run_round(snapshot: Path, round_id: str, *, engine: Engine | None = None) -> Path:
    if not re.fullmatch(r"nse_[a-z0-9_]{3,32}", round_id):
        raise ValueError(
            "round ID must start nse_ and contain lowercase letters/digits/underscores"
        )
    policy = EquityResearchPolicy()
    engine = get_engine() if engine is None else engine
    output = PROJECT_ROOT / "reports_out/equity_research" / round_id
    output.mkdir(parents=True, exist_ok=False)
    (output / "source").mkdir()
    source_hashes = {}
    sources = list((PROJECT_ROOT / "research/helios").rglob("*.py")) + [
        GATES_PATH,
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
        candidates=CANDIDATES,
        model=MODEL_PROTOCOL,
        source_commit=git_commit(),
        dirty=git_is_dirty(),
        source_hashes=source_hashes,
        source_manifest_sha256=sha256(snapshot / "manifest.json"),
        source_snapshot=str(snapshot),
        test_access=False,
        automatic_promotion=False,
        scope="hourly intraday; daily is calendar evidence; minute history insufficient",
        coverage="ex-post complete-session conditional study; excluded sessions stay unknown",
    )
    write_json(output / "protocol.json", protocol)
    roster = constituents((snapshot / "constituents.csv").read_bytes())
    inputs = [load_equity_inputs(snapshot, row["Symbol"], policy) for row in roster]
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
        source="yahoo_nse_research_prefix",
        interval="1h",
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
    gates = load_config(GATES_PATH, GatesConfig)
    with engine.begin() as connection:
        register_snapshot(connection, snapshot_record)
        store_gate_config(connection, gates, author="helios_equity_research")
        ml_experiment = register_experiment(
            connection,
            hypothesis=(
                "Fixed hourly classifier with disjoint TRAIN-tail expected-return calibration"
            ),
            params=MODEL_PROTOCOL
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
        for candidate in CANDIDATES:
            identifier = f"{round_id}_{candidate}"
            register_definition(connection, candidate_definition(round_id, candidate, model))
            for source in inputs:
                params = dict(
                    market="nse_cash",
                    symbol=source.symbol,
                    alpha_id=identifier,
                    policy_hash=config_hash(policy),
                    model_hash=model.model_hash,
                    calibration_hash=model.calibration_hash,
                    source_hashes=source_hashes,
                )
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
            f"{index}/150 {attempt['candidate']} {attempt['symbol']} {result.status.value}",
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
    )
    write_json(output / "summary.json", summary)
    print(f"Completed: {output / 'summary.json'}", flush=True)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--round-id", required=True)
    args = parser.parse_args()
    run_round(args.snapshot, args.round_id)


if __name__ == "__main__":
    main()
