"""Calibrate a preregistered saved LightGBM run, without fitting it again."""

import argparse
from dataclasses import asdict
from pathlib import Path

from helios.common.config import HeliosConfig
from helios.common.db import get_engine
from helios.common.lineage import RunContext
from helios.data.binance import sha256_file
from helios.ml.calibration import fit_valid_calibration, save_calibration, verified_source
from helios.registry.experiments import (
    ExperimentKind,
    ExperimentStatus,
    require_open_experiment,
    set_status,
)
from helios.registry.results import Split
from helios.sim.splits import split_window


class CalibrationProtocol(HeliosConfig):
    source_metrics_sha256: str
    method: str = "isotonic_increasing_clip"
    bins: int = 10
    fit_split: str = "valid"
    diagnostics: str = "VALID resubstitution; source early stopping also used VALID"
    test_access: bool = False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--experiment-id", required=True, type=int)
    args = parser.parse_args()
    protocol = CalibrationProtocol(source_metrics_sha256=sha256_file(args.source))
    source, predictions = verified_source(args.source)
    snapshot = source["lineage"]["data_snapshot_id"]
    context = RunContext.capture(protocol, snapshot, 0, reported=True)
    with get_engine().begin() as connection:
        experiment = require_open_experiment(connection, args.experiment_id)
        if (
            experiment.kind is not ExperimentKind.ML
            or experiment.snapshot_id != snapshot
            or experiment.params.get("protocol") != protocol.model_dump(mode="json")
            or experiment.status is not ExperimentStatus.PLANNED
        ):
            raise ValueError("exact source/calibration protocol must be preregistered once")
        set_status(connection, args.experiment_id, ExperimentStatus.RUNNING)
    frozen, output, report = fit_valid_calibration(
        predictions,
        split_window(Split.VALID, interval="1h"),
        source_metrics_sha256=sha256_file(args.source),
        model_sha256=source["artifact_hashes"]["lightgbm.joblib"],
        snapshot_id=snapshot,
    )
    lineage = asdict(context)
    lineage["created_at"] = context.created_at.isoformat()
    report.update(
        lineage=lineage,
        experiment_id=args.experiment_id,
        source=str(args.source),
        protocol=protocol.model_dump(mode="json"),
    )
    path = save_calibration(frozen, output, report, Path("reports_out/hourly_calibration"))
    with get_engine().begin() as connection:
        set_status(
            connection,
            args.experiment_id,
            ExperimentStatus.FINISHED,
            notes=f"VALID-only calibration evidence: {path}; SHA256 {sha256_file(path)}",
        )
    print(path)


if __name__ == "__main__":
    main()
