"""Freeze and preregister bounded shared-engine paper-strategy integration.

Exploratory VALID only. Never tunes candidates, changes gates, promotes or reads
TEST. Frozen execution may retain dirty development lineage without relabelling.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, default=str, allow_nan=False)
        stream.write("\n")


def freeze(args):
    from helios.common.lineage import PROJECT_ROOT, git_commit, git_is_dirty
    from helios.equities.config import EquityResearchPolicy

    if not re.fullmatch(r"nse_[a-z0-9_]{3,32}", args.round_id) or not 1 <= args.workers <= 4:
        raise ValueError("new NSE round ID and one to four isolated workers required")
    output = PROJECT_ROOT / "reports_out/equity_research" / args.round_id
    output.mkdir(parents=True, exist_ok=False)
    archive = output / "source"
    files = [
        *sorted((PROJECT_ROOT / "research/helios").rglob("*.py")),
        *sorted((PROJECT_ROOT / "configs/equities").glob("*.yaml")),
        PROJECT_ROOT / "pyproject.toml",
        PROJECT_ROOT / "uv.lock",
        Path(__file__).resolve(),
    ]
    hashes = {}
    for path in files:
        relative = path.relative_to(PROJECT_ROOT)
        copy = archive / relative
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, copy)
        hashes[relative.as_posix()] = digest(copy)
    for relative, expected in hashes.items():
        if digest(PROJECT_ROOT / relative) != expected:
            raise ValueError("source changed while freezing")
    (archive / "reports_out").symlink_to(PROJECT_ROOT / "reports_out", target_is_directory=True)
    launch = dict(
        project_root=str(PROJECT_ROOT),
        output=str(output),
        snapshot=str(args.snapshot.resolve()),
        model_lineage=str(args.model_lineage.resolve()),
        symbols=args.symbols,
        workers=args.workers,
        round_id=args.round_id,
        source_hashes=hashes,
        source_commit=git_commit(),
        dirty=git_is_dirty(),
        candidates=["closing_momentum", "orb_rvol", "noise_vwap"],
        execution_policy="paper_state_change_v1",
        prior_valid_exposure=True,
        automatic_promotion=False,
        test_access=False,
        purpose="Fixed prototype integration, not a fresh OOS profitability search",
        policy=EquityResearchPolicy(
            version="nse_minute_research_v2",
            interval="1m",
            session="reviewed_sessions_v2",
            commission_tax_proxy_bps=0,
        ).model_dump(mode="json"),
        source_snapshot=str(args.snapshot.resolve()),
        source_manifest_sha256=digest(args.snapshot.resolve() / "manifest.json"),
    )
    write(output / "protocol.json", launch)
    frozen_script = archive / Path(__file__).resolve().relative_to(PROJECT_ROOT)
    os.execv(
        sys.executable,
        [sys.executable, str(frozen_script), "--frozen-launch", str(output / "protocol.json")],
    )


def run(protocol_path):
    protocol = json.loads(protocol_path.read_text())
    output, root = Path(protocol["output"]), Path(protocol["project_root"])
    sys.path.insert(0, str(output / "source/research"))
    for relative, expected in protocol["source_hashes"].items():
        if digest(output / "source" / relative) != expected:
            raise ValueError("frozen source checksum mismatch")
    from dataclasses import asdict

    import pandas as pd
    from lightgbm import Booster
    from sqlalchemy import create_engine, text

    from helios.alpha.definition import AlphaDefinition, register_alpha_definition
    from helios.common.config import config_hash, load_config
    from helios.common.db import DatabaseSettings
    from helios.common.project_config import GatesConfig
    from helios.data.snapshots import Snapshot, SnapshotFile, compute_snapshot_id, register_snapshot
    from helios.equities.config import EquityResearchPolicy
    from helios.equities.model import EquityModel
    from helios.equities.paper_features import EXECUTION, FEATURE_SET, prepare_inputs
    from helios.equities.pipeline import registry_fingerprint
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

    os.chdir("/tmp")
    engine = create_engine(DatabaseSettings(_env_file=root / ".env").url(), pool_pre_ping=True)

    def fingerprints():
        answer = {}
        with engine.connect() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            for table, keys in (
                ("alpha_definitions", ("alpha_id", "version")),
                ("alpha_results", ("run_id",)),
                ("experiments", ("experiment_id",)),
            ):
                rows = connection.execute(text(f"SELECT to_jsonb(t) FROM {table} t")).scalars()
                answer[table] = {
                    ":".join(str(row[k]) for k in keys): hashlib.sha256(
                        json.dumps(row, sort_keys=True, default=str).encode()
                    ).hexdigest()
                    for row in rows
                }
        return answer

    before, original = registry_fingerprint(engine), fingerprints()
    write(output / "registry_before.json", dict(non_equity=before, prior_rows=original))
    policy = EquityResearchPolicy(
        version="nse_minute_research_v2",
        interval="1m",
        session="reviewed_sessions_v2",
        commission_tax_proxy_bps=0,
    )
    inputs, feature_protocol = prepare_inputs(
        Path(protocol["snapshot"]), tuple(protocol["symbols"]), policy
    )
    write(output / "feature_protocol.json", feature_protocol)
    (output / "inputs").mkdir()
    files, first, last, count = [], [], [], 0
    for symbol, candidates in inputs.items():
        source = next(iter(candidates.values()))
        path = output / "inputs" / (symbol + ".parquet")
        source.bars.to_parquet(path, index=False)
        first.append(int(source.bars.open_time.min()))
        last.append(int(source.bars.open_time.max()))
        count += len(source.bars)
        files.append(SnapshotFile(str(path.relative_to(root)), digest(path), path.stat().st_size))
        for name, source in candidates.items():
            path = output / "inputs" / (symbol + "_" + name + "_signals.parquet")
            pd.concat(
                [
                    source.features.open_time,
                    source.features.values,
                    source.features.available.add_suffix("_available"),
                ],
                axis=1,
            ).to_parquet(path, index=False)
            files.append(
                SnapshotFile(str(path.relative_to(root)), digest(path), path.stat().st_size)
            )
    path = output / "feature_protocol.json"
    files.append(SnapshotFile(str(path.relative_to(root)), digest(path), path.stat().st_size))
    snapshot = Snapshot(
        compute_snapshot_id(files),
        "upstox_nse_paper_features_conditional",
        "1m",
        list(inputs),
        min(first),
        max(last),
        len(files),
        count,
        sum(f.bytes for f in files),
        protocol["source_commit"],
        files,
    )
    write(output / "snapshot.json", asdict(snapshot))
    (output / "ml").mkdir()
    old = Path(protocol["model_lineage"])
    for name in ("model.txt", "calibration.json", "protocol.json"):
        shutil.copyfile(old / name, output / "ml" / name)
        if digest(old / name) != digest(output / "ml" / name):
            raise ValueError("model-lineage copy mismatch")
    calibration = json.loads((output / "ml/calibration.json").read_text())
    if (
        calibration["test_access"]
        or calibration["valid_observations_used_for_fit_or_calibration"]
        or digest(output / "ml/model.txt") != calibration["model_sha256"]
    ):
        raise ValueError("model lineage is not TRAIN-only")
    model = EquityModel(
        Booster(model_file=str(output / "ml/model.txt")),
        tuple(calibration["x"]),
        tuple(calibration["y"]),
        calibration["available_after_us"],
        calibration["model_sha256"],
        digest(output / "ml/calibration.json"),
        output / "ml",
    )
    gates = load_config(equity_gates_path(policy), GatesConfig)
    attempts = []
    with engine.begin() as connection:
        register_snapshot(connection, snapshot)
        store_gate_config(connection, gates, author="helios_equity_research")
        for candidate in protocol["candidates"]:
            definition = AlphaDefinition(
                alpha_id=protocol["round_id"] + "_" + candidate,
                version=1,
                name="EXPLORATORY NSE paper " + candidate,
                provenance="QUANT",
                feature_set_version=FEATURE_SET,
                horizon_family="H-MINUTE",
                horizon_periods=1,
                expression=candidate,
                author="helios_equity_research",
            )
            register_alpha_definition(connection, definition)
            for symbol, candidates in inputs.items():
                params = dict(
                    market="nse_cash",
                    symbol=symbol,
                    alpha_id=definition.alpha_id,
                    policy_hash=config_hash(policy),
                    model_hash=model.model_hash,
                    calibration_hash=model.calibration_hash,
                    source_hashes=protocol["source_hashes"],
                    execution_policy=EXECUTION,
                    input_hashes=candidates[candidate].hashes,
                )
                if protocol["workers"] != 1:
                    params["execution_workers"] = protocol["workers"]
                experiment = register_experiment(
                    connection,
                    hypothesis=f"Fixed paper prototype {candidate} integration on {symbol}",
                    params=params,
                    kind=ExperimentKind.ALPHA,
                    author="helios_equity_research",
                    code_commit=protocol["source_commit"],
                    config_hash=config_hash(policy),
                    snapshot_id=snapshot.snapshot_id,
                    notes=(
                        "Prior TRAIN/VALID exposure; frozen development source; no refit, "
                        "fresh OOS, TEST or promotion. Unchanged gates and exclusions."
                    ),
                )
                attempts.append(
                    dict(
                        candidate=candidate,
                        symbol=symbol,
                        alpha_id=definition.alpha_id,
                        experiment_id=experiment.experiment_id,
                    )
                )
    write(output / "preregistration.json", dict(attempts=attempts, calibration=calibration))
    results = []
    for i, attempt in enumerate(attempts, 1):
        print(f"START {i}/{len(attempts)} {attempt['candidate']} {attempt['symbol']}", flush=True)
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
                inputs[attempt["symbol"]][attempt["candidate"]],
                snapshot.snapshot_id,
                model,
                protocol["source_hashes"],
                workers=protocol["workers"],
                execution_policy=EXECUTION,
            ),
        )
        with engine.begin() as connection:
            set_status(connection, attempt["experiment_id"], ExperimentStatus.FINISHED)
        row = attempt | dict(
            run_id=result.run_id,
            status=result.status.value,
            sharpe=result.sharpe,
            fitness=result.fitness,
            gates=result.gate_results,
            artifact=result.evaluation_json["artifact"],
            artifact_sha256=result.evaluation_json["artifact_sha256"],
        )
        results.append(row)
        with (output / "outcomes.jsonl").open("a") as stream:
            stream.write(json.dumps(row, default=str) + "\n")
        print(f"DONE {i}/{len(attempts)} {row['status']} Sharpe={row['sharpe']}", flush=True)
    after, current = registry_fingerprint(engine), fingerprints()
    if before != after or any(
        current[t].get(k) != v for t, rows in original.items() for k, v in rows.items()
    ):
        raise ValueError("pre-existing research or TEST audit changed")
    write(
        output / "history_checks.json",
        dict(
            all_prior_rows_unchanged=True,
            before_counts={t: len(r) for t, r in original.items()},
            after_counts={t: len(r) for t, r in current.items()},
        ),
    )
    write(
        output / "summary.json",
        dict(
            round_id=protocol["round_id"],
            market="nse_cash",
            snapshot_id=snapshot.snapshot_id,
            protocol_sha256=digest(protocol_path),
            results=results,
            model_hash=model.model_hash,
            calibration_hash=model.calibration_hash,
            dirty=protocol["dirty"],
            source_commit=protocol["source_commit"],
            registry_before=before,
            registry_after=after,
            crypto_unchanged=True,
            test_accesses=0,
            promoted=0,
            interval="1m",
            research_symbols=protocol["symbols"],
            prior_valid_exposure=True,
            execution_policy=EXECUTION,
            scope=protocol["purpose"],
            model_reused_for_lineage_only=True,
        ),
    )
    print("COMPLETED all fixed paper-strategy integration attempts", flush=True)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--frozen-launch":
        run(Path(sys.argv[2]))
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--snapshot", type=Path, required=True)
        parser.add_argument("--model-lineage", type=Path, required=True)
        parser.add_argument("--round-id", required=True)
        parser.add_argument("--symbols", nargs="+", default=["RELIANCE"])
        parser.add_argument("--workers", type=int, default=4)
        freeze(parser.parse_args())
