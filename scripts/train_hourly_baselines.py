"""Run the preregistered fixed hourly TRAIN/VALID comparison, never TEST (125)."""

import argparse
import json
from pathlib import Path

from helios.common.db import get_engine
from helios.common.lineage import RunContext
from helios.ml.hourly_baselines import (
    HourlyBaselineConfig,
    fit_hourly_baselines,
    fixed_protocol,
    save_baseline_run,
)
from helios.ml.hourly_inputs import load_hourly_pair
from helios.registry.experiments import ExperimentKind, require_open_experiment


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-id", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("reports_out/hourly_linear"))
    args = parser.parse_args()
    config = HourlyBaselineConfig()
    with get_engine().begin() as connection:
        experiment = require_open_experiment(connection, args.experiment_id)
    if (
        experiment.kind is not ExperimentKind.ML
        or experiment.snapshot_id is None
        or experiment.params.get("protocol") != fixed_protocol(config)
    ):
        raise ValueError("experiment must preregister this exact fixed ML protocol and snapshot")
    # Check clean lineage before loading observations; trainer records the same source.
    RunContext.capture(config, experiment.snapshot_id, config.seed, reported=True)
    train, valid, evidence = load_hourly_pair(experiment.snapshot_id, config)
    result = fit_hourly_baselines(train, valid, config, reported=True)
    result.report.update(experiment_id=experiment.experiment_id, input_evidence=evidence)
    path = save_baseline_run(result, args.output_dir)
    print(
        json.dumps(
            dict(
                metrics_path=str(path),
                ridge=result.report["ridge"],
                logistic=result.report["logistic"],
                convergence=result.report["convergence"],
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
