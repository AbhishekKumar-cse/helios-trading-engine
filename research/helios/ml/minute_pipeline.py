"""One preregistered minute ML attempt through the existing causal pipeline."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from helios.alpha.definition import register_alpha_definition
from helios.common.config import config_hash
from helios.common.db import get_engine
from helios.common.lineage import RunContext
from helios.common.project_config import (
    HorizonFamily,
    load_fees,
    load_gates,
    load_minute_stage,
    load_splits,
)
from helios.common.types import DecisionLineage
from helios.data.binance import sha256_file
from helios.ml.calibration import fit_valid_calibration, save_calibration
from helios.ml.dataset import DatasetConfig
from helios.ml.hourly_baselines import FEATURES, save_baseline_run
from helios.ml.hourly_inputs import load_hourly_pair
from helios.ml.hourly_lightgbm import LightGBMConfig, fit_lightgbm
from helios.ml.prediction_alpha import MLAlphaPolicy, fit_train_payoffs, prediction_to_alpha
from helios.ml.registered_alpha import frozen_definition, read_frozen_ml
from helios.registry.experiments import (
    ExperimentKind,
    ExperimentStatus,
    require_open_experiment,
    set_status,
)
from helios.registry.results import Split
from helios.sim.evaluate import EvaluationConfig, evaluate


def minute_ml_config() -> LightGBMConfig:
    return LightGBMConfig(
        dataset=DatasetConfig(features=FEATURES, interval="1m"), symbols=("BTCUSDT",)
    )


def minute_ml_protocol() -> dict[str, Any]:
    return dict(
        version="minute_ml_pipeline_v1",
        alpha_id="minute_ml_v1",
        config=minute_ml_config().model_dump(mode="json"),
        stage=load_minute_stage().model_dump(mode="json"),
        fees=load_fees().model_dump(mode="json"),
        gates=load_gates().model_dump(mode="json"),
        splits=load_splits().model_dump(mode="json"),
        fit="TRAIN only; fixed LightGBM; VALID binary-logloss stopping",
        calibration="VALID isotonic; available only after VALID end",
        payoffs="TRAIN conditional positive/nonpositive mean returns",
        window=168,
        cost_sides=2,
        evaluate="VALID via frozen typed availability and shared simulator/gates",
        test_access=False,
        tune=False,
        retain_all=True,
        prior_exposure=(
            "All hourly research and eleven rejected minute quantitative VALID outcomes "
            "and cost curves are known. No minute ML fit or measurement yet."
        ),
    )


def run_minute_ml(experiment_id: int, root: Path = Path("reports_out/minute_ml")) -> Path:
    config, protocol, engine = minute_ml_config(), minute_ml_protocol(), get_engine()
    destination = root / f"experiment-{experiment_id}"
    if destination.exists():
        raise ValueError("retain this ML attempt; automatic reruns are forbidden")
    with engine.begin() as connection:
        experiment = require_open_experiment(connection, experiment_id)
        if (
            experiment.kind is not ExperimentKind.ML
            or experiment.status is not ExperimentStatus.PLANNED
            or experiment.params.get("protocol") != protocol
            or experiment.snapshot_id is None
        ):
            raise ValueError("exact minute ML pipeline must be preregistered once")
        context = RunContext.capture(config, experiment.snapshot_id, 0, reported=True)
        destination.mkdir(parents=True, exist_ok=False)
        set_status(connection, experiment_id, ExperimentStatus.RUNNING)
    journal: dict[str, Any] = dict(experiment_id=experiment_id, status="RUNNING", stages={})
    manifest = destination / "outcome.json"

    def retain() -> None:
        manifest.write_text(json.dumps(journal, indent=2, allow_nan=False) + "\n")

    def finished(stage: str, path: Path) -> None:
        journal["stages"][stage] = dict(path=str(path), sha256=sha256_file(path))
        retain()
        print(stage + ": " + str(path), flush=True)

    retain()
    try:
        train, valid, inputs = load_hourly_pair(experiment.snapshot_id, config)
        fit = fit_lightgbm(train, valid, config)
        fit.report.update(experiment_id=experiment_id, input_evidence=inputs)
        source = save_baseline_run(fit, destination / "model")
        finished("fit", source)
        frozen, predictions, report = fit_valid_calibration(
            fit.predictions,
            valid.window,
            source_metrics_sha256=sha256_file(source),
            model_sha256=sha256_file(source.parent / "lightgbm.joblib"),
            snapshot_id=experiment.snapshot_id,
        )
        base_lineage = asdict(context) | dict(created_at=context.created_at.isoformat())
        report.update(
            source=str(source),
            lineage=base_lineage,
            protocol=dict(test_access=False, method="VALID isotonic"),
        )
        calibration = save_calibration(frozen, predictions, report, destination / "calibration")
        finished("calibration", calibration)
        policy = MLAlphaPolicy(
            calibration=frozen, payoffs=fit_train_payoffs(train), fees=load_fees()
        )
        lineage = DecisionLineage(
            alpha_id="minute_ml_v1",
            alpha_version=1,
            feature_set_version=config.dataset.feature_set_version,
            horizon_family=HorizonFamily.MINUTE,
            code_commit=context.code_commit,
            config_hash=config_hash(policy),
            snapshot_id=experiment.snapshot_id,
            seed=0,
            model_hash=frozen.model_sha256,
        )
        output = prediction_to_alpha(fit.predictions, policy, lineage)
        alpha_dir = destination / "alpha"
        alpha_dir.mkdir()
        output.diagnostics.to_parquet(alpha_dir / "diagnostics.parquet", index=False)
        (alpha_dir / "policy.json").write_text(policy.model_dump_json(indent=2) + "\n")
        with (alpha_dir / "alpha_values.jsonl").open("x") as handle:
            for value in output.values:
                handle.write(value.model_dump_json() + "\n")
        alpha_path = alpha_dir / "metrics.json"
        alpha_path.write_text(
            json.dumps(
                dict(
                    experiment_id=experiment_id,
                    calibration=str(calibration),
                    lineage=base_lineage | dict(config_hash=config_hash(policy)),
                    protocol=dict(
                        calibration_metrics_sha256=sha256_file(calibration),
                        test_access=False,
                        post_calibration_only=True,
                        window=168,
                        cost_sides=2,
                    ),
                    n_rows=len(output.values),
                    n_available=int(output.diagnostics.available.sum()),
                    n_diagnostic=int(output.diagnostics.diagnostic_alpha.notna().sum()),
                    limitations=[
                        "Historical VALID predates the fitted map: typed values unavailable.",
                        "Diagnostic alpha is retrospective; it cannot replace typed availability.",
                    ],
                    artifact_hashes={
                        name: sha256_file(alpha_dir / name)
                        for name in ("policy.json", "alpha_values.jsonl", "diagnostics.parquet")
                    },
                ),
                indent=2,
                allow_nan=False,
            )
            + "\n"
        )
        finished("alpha", alpha_path)
        definition = frozen_definition(read_frozen_ml(alpha_path))
        with engine.begin() as connection:
            register_alpha_definition(connection, definition)
        result = evaluate(
            "minute_ml_v1",
            Split.VALID,
            experiment_id,
            engine=engine,
            config=EvaluationConfig(interval="1m"),
            output_dir=destination / "evaluation",
        )
        journal.update(
            run_id=result.run_id,
            result_status=result.status.value,
            evaluation=result.evaluation_json,
        )
        with engine.begin() as connection:
            set_status(connection, experiment_id, ExperimentStatus.FINISHED)
        journal["status"] = "FINISHED"
        retain()
        return manifest
    except Exception as exc:
        journal.update(status="FAILED", error_type=type(exc).__name__)
        retain()
        with engine.begin() as connection:
            set_status(connection, experiment_id, ExperimentStatus.ABANDONED)
        raise
