"""Resume preregistered NSE work after infrastructure failure, without refitting.

Completed result rows and source archives are immutable. A computed artifact
whose DB transaction failed is recovered without replay; its unobserved runtime
is NULL. Independent unfinished experiments may run concurrently, while each
experiment keeps its frozen session worker policy and chronological execution.
"""

import argparse
import hashlib
import json
import multiprocessing
import os
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, localcontext
from pathlib import Path


def bootstrap(round_id):
    repo = Path(__file__).resolve().parents[1]
    runtime = repo / "reports_out/equity_runtime" / round_id
    sys.path.insert(0, str(runtime / "research"))
    from lightgbm import Booster
    from sqlalchemy import create_engine

    from helios.common.db import DatabaseSettings
    from helios.equities import pipeline
    from helios.equities.config import EquityResearchPolicy
    from helios.equities.model import EquityModel

    assert Path(pipeline.__file__).is_relative_to(runtime)
    output = repo / "reports_out/equity_research" / round_id
    protocol = json.loads((output / "protocol.json").read_text())
    snapshot = json.loads((output / "snapshot.json").read_text())
    calibration = json.loads((output / "ml/calibration.json").read_text())
    model = EquityModel(
        Booster(model_file=str(output / "ml/model.txt")),
        tuple(calibration["x"]),
        tuple(calibration["y"]),
        calibration["available_after_us"],
        calibration["model_sha256"],
        pipeline.sha256(output / "ml/calibration.json"),
        output / "ml",
    )
    engine = create_engine(DatabaseSettings(_env_file=repo / ".env").url(), pool_pre_ping=True)
    return (
        repo,
        runtime,
        output,
        protocol,
        snapshot,
        EquityResearchPolicy(**protocol["policy"]),
        model,
        engine,
    )


def outcome(attempt, result):
    return attempt | dict(
        run_id=result.run_id,
        status=result.status.value,
        sharpe=None if result.sharpe is None else float(result.sharpe),
        fitness=None if result.fitness is None else float(result.fitness),
        gates=result.gate_results,
        artifact=result.evaluation_json["artifact"],
        artifact_sha256=result.evaluation_json["artifact_sha256"],
    )


def recover_artifact(path, attempt, engine):
    """Persist already-computed accounting; no simulation, fitting or TEST read."""
    import numpy as np
    from sqlalchemy import text

    from helios.data.equities import sha256
    from helios.registry.experiments import ExperimentStatus, set_status
    from helios.registry.results import AlphaResult, Split, record_result
    from helios.sim.fitness import fitness

    evidence = json.loads(path.read_text())
    protocol, lineage = evidence["protocol"], evidence["source"]
    assert evidence["status"] in ("REJECTED", "INVALID") and not evidence["test_access"]
    assert protocol["definition"]["alpha_id"] == attempt["alpha_id"]
    assert not any(g["passed"] for g in evidence["gates"]["outcomes"] if g["gate"] == "G7")
    metrics = evidence["diagnostics"].get("base", {}).get("metrics")
    returns = np.asarray([r["net_return"] for r in evidence["series"]])
    slots = 375 if protocol["policy"]["interval"] == "1m" else 6
    turnover = (
        float(np.mean([r["turnover"] / slots for r in evidence["series"]])) if metrics else None
    )
    fit = (
        fitness(
            metrics["annual_sharpe"],
            metrics["annual_return"],
            turnover,
            floor=protocol["gates"]["fitness_turnover_floor"],
        )
        if metrics
        else None
    )
    cumulative = np.cumsum(returns)
    drawdown = (
        float(np.min(cumulative - np.maximum.accumulate(np.r_[0.0, cumulative])[1:]))
        if metrics
        else None
    )
    stress = evidence["costs"]["points"][1]["metrics"]["metrics"] if metrics else None
    fraction = (
        float(np.mean([r["metrics"]["total_return"] > 0 for r in evidence["stability"]["months"]]))
        if metrics
        else None
    )

    def number(value):
        if value is None:
            return None
        with localcontext() as context:
            context.prec = 50
            return Decimal(str(value)).quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP)

    result = AlphaResult(
        run_id=path.stem,
        experiment_id=attempt["experiment_id"],
        alpha_id=attempt["alpha_id"],
        version=1,
        split=Split.VALID,
        snapshot_id=evidence["snapshot_id"],
        gate_config_id=protocol["gates"]["version"],
        status=evidence["status"],
        sharpe=number(metrics["annual_sharpe"] if metrics else None),
        annual_return=number(metrics["annual_return"] if metrics else None),
        turnover=number(turnover),
        fitness=number(fit),
        periods=metrics["n_periods"] if metrics else 0,
        max_drawdown=number(drawdown),
        hit_rate=number(float(np.mean(returns > 0)) if metrics else None),
        cost_stress_sharpe=number(stress["annual_sharpe"] if stress else None),
        stability_positive_fraction=number(fraction),
        runtime_seconds=None,
        gate_results={g["gate"]: g["passed"] for g in evidence["gates"]["outcomes"]},
        code_commit=lineage["code_commit"],
        dirty=lineage["dirty"],
        seed=protocol["policy"]["seed"],
        config_hash=hashlib.sha256(json.dumps(protocol, sort_keys=True).encode()).hexdigest(),
        evaluation_json=dict(
            status=evidence["status"],
            market="nse_cash",
            artifact=str(path),
            artifact_sha256=sha256(path),
            validity=evidence["validity"],
            protocol=protocol,
        ),
    )
    with engine.begin() as connection:
        stored = record_result(connection, result)
        set_status(connection, attempt["experiment_id"], ExperimentStatus.FINISHED)
        connection.execute(
            text("""INSERT INTO audit_events
            (ts,actor,action,subject,after_hash,justification,payload)
            VALUES (:ts,'equity_recovery','NSE_ARTIFACT_RECOVERY',:subject,:hash,:why,
                    CAST(:payload AS jsonb))"""),
            dict(
                ts=int(datetime.now(UTC).timestamp() * 1_000_000),
                subject=result.run_id,
                hash=sha256(path),
                why="DB unavailable after artifact creation; retained computation without replay",
                payload=json.dumps(
                    dict(
                        experiment_id=attempt["experiment_id"],
                        artifact=str(path),
                        artifact_sha256=sha256(path),
                        replayed=False,
                        runtime_seconds=None,
                    )
                ),
            ),
        )
    return stored


def execute_attempt(round_id, attempt, retry_preflight=False):
    _, _, output, protocol, snapshot, policy, model, engine = bootstrap(round_id)
    from helios.equities.inputs import load_equity_inputs
    from helios.registry.experiments import ExperimentStatus, get_experiment, set_status
    from helios.registry.results import Split
    from helios.sim.equity_evaluation import EquityEvaluationContext
    from helios.sim.evaluate import evaluate

    with engine.begin() as connection:
        state = get_experiment(connection, attempt["experiment_id"]).status
        if state is not ExperimentStatus.PLANNED and not (
            state is ExperimentStatus.RUNNING and retry_preflight
        ):
            raise ValueError("only never-started experiments may be resumed through simulation")
        if state is ExperimentStatus.PLANNED:
            set_status(connection, attempt["experiment_id"], ExperimentStatus.RUNNING)
    source = load_equity_inputs(Path(protocol["source_snapshot"]), attempt["symbol"], policy)
    kwargs = (
        dict(workers=protocol.get("execution_workers", 1))
        if "workers" in EquityEvaluationContext.__dataclass_fields__
        else {}
    )
    result = evaluate(
        attempt["alpha_id"],
        Split.VALID,
        attempt["experiment_id"],
        engine=engine,
        output_dir=output / "evaluations",
        reported=False,
        equity=EquityEvaluationContext(
            policy, source, snapshot["snapshot_id"], model, protocol["source_hashes"], **kwargs
        ),
    )
    with engine.begin() as connection:
        set_status(connection, attempt["experiment_id"], ExperimentStatus.FINISHED)
    return outcome(attempt, result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("round_id")
    parser.add_argument("--experiments-in-parallel", type=int, choices=(1, 2, 3, 4), default=1)
    parser.add_argument("--retry-lineage-preflight", nargs="*", type=int, default=[])
    parser.add_argument("--failure-log", type=Path)
    args = parser.parse_args()
    repo, runtime, output, protocol, snapshot, policy, model, engine = bootstrap(args.round_id)
    from sqlalchemy import text

    from helios.data.equities import sha256, write_json
    from helios.equities.pipeline import registry_fingerprint
    from helios.registry.experiments import ExperimentStatus, get_experiment
    from helios.registry.results import get_result

    if (output / "summary.json").exists():
        raise ValueError("completed immutable rounds cannot be resumed")
    for name, digest in protocol["source_hashes"].items():
        assert sha256(runtime / name) == sha256(output / "source" / name) == digest
    for item in snapshot["files"]:
        assert sha256(repo / item["path"]) == item["sha256"]
    assert (
        sha256(Path(protocol["source_snapshot"]) / "manifest.json")
        == protocol["source_manifest_sha256"]
    )
    assert model.model_hash == sha256(output / "ml/model.txt")
    before = json.loads((output / "registry_before.json").read_text())
    assert registry_fingerprint(engine) == before
    attempts = json.loads((output / "preregistration.json").read_text())["attempts"]
    rows = [json.loads(line) for line in (output / "outcomes.jsonl").read_text().splitlines()]
    by_experiment = {r["experiment_id"]: r for r in rows}
    with engine.connect() as connection:
        for row in rows:
            stored = get_result(connection, row["run_id"])
            assert stored.experiment_id == row["experiment_id"]
            assert (
                stored.evaluation_json["artifact_sha256"]
                == row["artifact_sha256"]
                == sha256(Path(row["artifact"]))
            )
    recovery_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    driver_archive = output / f"recovery_{recovery_id}_driver.py"
    with Path(__file__).open("rb") as source, driver_archive.open("xb") as destination:
        shutil.copyfileobj(source, destination)
    audit = dict(
        version="nse_infrastructure_recovery_v1",
        started_at=datetime.now(UTC).isoformat(),
        original_protocol_sha256=sha256(output / "protocol.json"),
        driver_sha256=sha256(Path(__file__)),
        driver_archive=driver_archive.name,
        source_unchanged=True,
        refit=False,
        parallel_independent_experiments=args.experiments_in_parallel,
        per_experiment_session_workers=protocol.get("execution_workers", 1),
        completed_before=len(rows),
        recovered_artifacts=[],
        runtime_of_recovered_artifacts=None,
    )
    if args.retry_lineage_preflight:
        if args.failure_log is None:
            raise ValueError("preflight retry requires retained infrastructure failure evidence")
        failure = args.failure_log.read_text()
        if (
            "LineageError" not in failure
            or "unable to get current working directory" not in failure
        ):
            raise ValueError("preflight retry requires the diagnosed lineage directory failure")
        audit["open_attempt_preflight_retries"] = args.retry_lineage_preflight
        audit["coordinator_failure_log_sha256"] = sha256(args.failure_log)
        audit["coordinator_failure_log"] = str(args.failure_log.resolve())
        audit["retry_notice"] = (
            "Coordinator reported LineageError; these open attempts have no stored result "
            "or computed artifact. Unchanged original preregistration, model and policy retained."
        )
    write_json(output / f"recovery_{recovery_id}_before.json", audit)

    def append(row):
        with (output / "outcomes.jsonl").open("a") as handle:
            handle.write(json.dumps(row) + "\n")
        rows.append(row)
        by_experiment[row["experiment_id"]] = row
        print(
            f"{len(rows)}/{len(attempts)} {row['candidate']} {row['symbol']} {row['status']}",
            flush=True,
        )

    known = {row["run_id"] for row in rows}
    for path in sorted((output / "evaluations").glob("*.json")):
        if path.stem in known:
            continue
        evidence = json.loads(path.read_text())
        assert evidence["source_hashes"] == protocol["source_hashes"]
        assert evidence["snapshot_id"] == snapshot["snapshot_id"]
        assert evidence["protocol"]["model_hash"] == model.model_hash
        assert evidence["protocol"]["calibration_hash"] == model.calibration_hash
        symbols = {fill["symbol"] for fill in evidence["fills"]}
        possible = [
            a
            for a in attempts
            if a["alpha_id"] == evidence["protocol"]["definition"]["alpha_id"]
            and a["experiment_id"] not in by_experiment
            and a["symbol"] in symbols
        ]
        if len(possible) != 1:
            raise ValueError("orphan artifact identity is ambiguous; refuse automatic replay")
        attempt = possible[0]
        with engine.connect() as connection:
            existing = (
                connection.execute(
                    text("SELECT run_id FROM alpha_results WHERE experiment_id=:id"),
                    dict(id=attempt["experiment_id"]),
                )
                .scalars()
                .all()
            )
        if existing:
            if existing != [path.stem]:
                raise ValueError("orphan artifact conflicts with registry")
            with engine.connect() as connection:
                result = get_result(connection, existing[0])
        else:
            result = recover_artifact(path, attempt, engine)
        append(outcome(attempt, result))
        audit["recovered_artifacts"].append(
            dict(run_id=result.run_id, sha256=sha256(path), replayed=False)
        )
    pending = [a for a in attempts if a["experiment_id"] not in by_experiment]
    with engine.connect() as connection:
        for attempt in pending:
            state = get_experiment(connection, attempt["experiment_id"]).status
            assert state is ExperimentStatus.PLANNED or (
                state is ExperimentStatus.RUNNING
                and attempt["experiment_id"] in args.retry_lineage_preflight
            )
    # A stable Linux working directory avoids transient Windows/OneDrive inode
    # invalidation during spawn. All research/data/output paths are absolute.
    os.chdir("/tmp")
    with ProcessPoolExecutor(
        max_workers=args.experiments_in_parallel, mp_context=multiprocessing.get_context("spawn")
    ) as pool:
        futures = [
            pool.submit(
                execute_attempt,
                args.round_id,
                attempt,
                attempt["experiment_id"] in args.retry_lineage_preflight,
            )
            for attempt in pending
        ]
        for future in as_completed(futures):
            append(future.result())
    after = registry_fingerprint(engine)
    assert before == after
    for name, digest in protocol["source_hashes"].items():
        assert sha256(runtime / name) == digest
    assert len(rows) == len(attempts)
    ordered = [by_experiment[a["experiment_id"]] for a in attempts]
    write_json(
        output / f"recovery_{recovery_id}_after.json",
        audit
        | dict(
            finished_at=datetime.now(UTC).isoformat(),
            completed_after=len(rows),
            crypto_unchanged=True,
            test_accesses=after["test_accesses"],
        ),
    )
    write_json(
        output / "summary.json",
        dict(
            round_id=args.round_id,
            market="nse_cash",
            snapshot_id=snapshot["snapshot_id"],
            protocol_sha256=sha256(output / "protocol.json"),
            results=ordered,
            model_hash=model.model_hash,
            calibration_hash=model.calibration_hash,
            dirty=protocol["dirty"],
            source_commit=protocol["source_commit"],
            test_accesses=0,
            registry_before=before,
            registry_after=after,
            crypto_unchanged=True,
            promoted=0,
            scope=protocol["scope"],
            interval=policy.interval,
            research_symbols=sorted({r["symbol"] for r in rows}),
            model_symbols=snapshot["symbols"],
            infrastructure_recovery=f"recovery_{recovery_id}_after.json",
        ),
    )
    print(f"Completed: {output / 'summary.json'}", flush=True)


if __name__ == "__main__":
    main()
