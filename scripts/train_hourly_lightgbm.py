import argparse
import json
from pathlib import Path

from helios.common.db import get_engine
from helios.common.lineage import RunContext
from helios.ml.hourly_baselines import save_baseline_run
from helios.ml.hourly_inputs import load_hourly_pair
from helios.ml.hourly_lightgbm import LightGBMConfig, fit_lightgbm, lightgbm_protocol
from helios.registry.experiments import ExperimentKind, require_open_experiment


def main() -> None:
    parser = argparse.ArgumentParser(description="Fixed TRAIN/VALID LightGBM; no TEST")
    parser.add_argument("--experiment-id", required=True, type=int)
    args = parser.parse_args()
    config = LightGBMConfig()
    with get_engine().begin() as connection:
        experiment = require_open_experiment(connection, args.experiment_id)
    if (
        experiment.kind is not ExperimentKind.ML
        or experiment.snapshot_id is None
        or experiment.params.get("protocol") != lightgbm_protocol(config)
    ):
        raise ValueError("exact LightGBM protocol must be preregistered")
    RunContext.capture(config, experiment.snapshot_id, config.seed, reported=True)
    train, valid, evidence = load_hourly_pair(experiment.snapshot_id, config)
    run = fit_lightgbm(train, valid, config)
    run.report.update(experiment_id=experiment.experiment_id, input_evidence=evidence)
    path = save_baseline_run(run, Path("reports_out/hourly_lightgbm"))
    print(
        json.dumps(
            dict(
                metrics_path=str(path),
                metrics=run.report["metrics"],
                best_iteration=run.report["best_iteration"],
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
