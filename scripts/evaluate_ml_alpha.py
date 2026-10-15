"""Register and evaluate a preregistered frozen ML alpha on VALID once (145)."""

import argparse
import json
from pathlib import Path

from sqlalchemy import text

from helios.alpha.definition import register_alpha_definition
from helios.common.db import get_engine
from helios.common.lineage import git_is_dirty
from helios.ml.registered_alpha import frozen_definition, ml_evaluation_protocol, read_frozen_ml
from helios.registry.api import get_alpha
from helios.registry.experiments import (
    ExperimentKind,
    ExperimentStatus,
    require_open_experiment,
    set_status,
)
from helios.registry.results import Split
from helios.sim.evaluate import EvaluationConfig, evaluate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metrics", type=Path, required=True)
    parser.add_argument("--experiment-id", type=int, required=True)
    args = parser.parse_args()
    if git_is_dirty():
        raise ValueError("reported ML evaluation requires clean source")
    artifact = read_frozen_ml(args.metrics)
    definition = frozen_definition(artifact)
    protocol = ml_evaluation_protocol(artifact)
    destination = Path("reports_out/hourly_ml_evaluation") / f"experiment-{args.experiment_id}.json"
    if destination.exists():
        raise ValueError("retain the existing ML evaluation manifest; no automatic reruns")
    engine = get_engine()
    with engine.begin() as connection:
        experiment = require_open_experiment(connection, args.experiment_id)
        if (
            experiment.kind is not ExperimentKind.ML
            or experiment.status is not ExperimentStatus.PLANNED
            or experiment.snapshot_id != artifact.policy.calibration.snapshot_id
            or experiment.params.get("protocol") != protocol
        ):
            raise ValueError("exact frozen VALID ML evaluation must be preregistered once")
        if connection.execute(
            text("SELECT count(*) FROM alpha_results WHERE experiment_id=:id"),
            {"id": args.experiment_id},
        ).scalar_one():
            raise ValueError("experiment already contains results")
        exists = connection.execute(
            text("SELECT count(*) FROM alpha_definitions WHERE alpha_id=:id AND version=:version"),
            {"id": definition.alpha_id, "version": definition.version},
        ).scalar_one()
        if exists:
            stored = get_alpha(connection, definition.alpha_id, definition.version)
            expected = definition.to_registry()
            if (
                stored.spec != expected.spec
                or stored.provenance != expected.provenance
                or stored.feature_set_version != expected.feature_set_version
                or stored.horizon_family != expected.horizon_family
                or stored.horizon_periods != expected.horizon_periods
            ):
                raise ValueError("existing immutable ML definition conflicts")
        else:
            register_alpha_definition(connection, definition)
        set_status(connection, args.experiment_id, ExperimentStatus.RUNNING)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x") as handle:
        json.dump(
            dict(experiment_id=args.experiment_id, protocol=protocol, status="RUNNING"), handle
        )
    outcomes = []
    for symbol in protocol["symbols"]:
        result = evaluate(
            definition.alpha_id,
            Split.VALID,
            args.experiment_id,
            engine=engine,
            config=EvaluationConfig(symbol=symbol, version=definition.version),
        )
        outcomes.append(
            dict(
                symbol=symbol,
                run_id=result.run_id,
                status=result.status.value,
                artifact=result.evaluation_json["artifact"],
                artifact_sha256=result.evaluation_json["artifact_sha256"],
            )
        )
        destination.write_text(
            json.dumps(
                dict(
                    experiment_id=args.experiment_id,
                    protocol=protocol,
                    status="RUNNING",
                    outcomes=outcomes,
                ),
                indent=2,
            )
            + "\n"
        )
        print(json.dumps(outcomes[-1]), flush=True)
    with engine.begin() as connection:
        set_status(connection, args.experiment_id, ExperimentStatus.FINISHED)
    destination.write_text(
        json.dumps(
            dict(
                experiment_id=args.experiment_id,
                protocol=protocol,
                status="FINISHED",
                outcomes=outcomes,
            ),
            indent=2,
        )
        + "\n"
    )
    print(destination)


if __name__ == "__main__":
    main()
