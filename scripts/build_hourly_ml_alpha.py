"""Generate frozen ML alpha evidence; historical fitting rows remain unavailable."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from helios.common.config import HeliosConfig, config_hash
from helios.common.db import get_engine
from helios.common.lineage import RunContext
from helios.common.project_config import HorizonFamily, load_fees
from helios.common.types import DecisionLineage
from helios.data.binance import sha256_file
from helios.ml.calibration import IsotonicMap, verified_source
from helios.ml.hourly_inputs import load_hourly_pair
from helios.ml.hourly_lightgbm import LightGBMConfig
from helios.ml.prediction_alpha import MLAlphaPolicy, fit_train_payoffs, prediction_to_alpha
from helios.registry.experiments import (
    ExperimentKind,
    ExperimentStatus,
    require_open_experiment,
    set_status,
)


class AlphaProtocol(HeliosConfig):
    calibration_metrics_sha256: str
    payoff_fit: str = "TRAIN conditional mean positive/nonpositive horizon return, per symbol"
    window: int = 168
    cost_sides: int = 2
    post_calibration_only: bool = True
    test_access: bool = False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration", required=True, type=Path)
    parser.add_argument("--experiment-id", required=True, type=int)
    args = parser.parse_args()
    protocol = AlphaProtocol(calibration_metrics_sha256=sha256_file(args.calibration))
    calibration = json.loads(args.calibration.read_text())
    for name, digest in calibration["artifact_hashes"].items():
        if sha256_file(args.calibration.parent / name) != digest:
            raise ValueError("calibration artifact changed")
    frozen = IsotonicMap.model_validate_json(
        (args.calibration.parent / "isotonic.json").read_text()
    )
    source_path = Path(calibration["source"])
    if sha256_file(source_path) != frozen.source_metrics_sha256:
        raise ValueError("calibration source metrics changed")
    source, predictions = verified_source(source_path)
    RunContext.capture(protocol, frozen.snapshot_id, 0, reported=True)
    with get_engine().begin() as connection:
        experiment = require_open_experiment(connection, args.experiment_id)
        if (
            experiment.kind is not ExperimentKind.ML
            or experiment.snapshot_id != frozen.snapshot_id
            or experiment.params.get("protocol") != protocol.model_dump(mode="json")
            or experiment.status is not ExperimentStatus.PLANNED
        ):
            raise ValueError("exact ML alpha transformation must be preregistered once")
        set_status(connection, args.experiment_id, ExperimentStatus.RUNNING)
    config = LightGBMConfig.model_validate(source["protocol"]["config"])
    train, _, input_evidence = load_hourly_pair(frozen.snapshot_id, config)
    policy = MLAlphaPolicy(calibration=frozen, payoffs=fit_train_payoffs(train), fees=load_fees())
    context = RunContext.capture(policy, frozen.snapshot_id, 0, reported=True)
    lineage = DecisionLineage(
        alpha_id="hourly_ml_v1",
        alpha_version=1,
        feature_set_version=config.dataset.feature_set_version,
        horizon_family=HorizonFamily.HOURLY,
        code_commit=context.code_commit,
        config_hash=config_hash(policy),
        snapshot_id=frozen.snapshot_id,
        seed=0,
        model_hash=frozen.model_sha256,
    )
    output = prediction_to_alpha(predictions, policy, lineage)
    destination = Path("reports_out/hourly_ml_alpha") / str(uuid4())
    destination.mkdir(parents=True, exist_ok=False)
    output.diagnostics.to_parquet(destination / "diagnostics.parquet", index=False)
    with (destination / "alpha_values.jsonl").open("x") as handle:
        for value in output.values:
            handle.write(value.model_dump_json() + "\n")
    policy_path = destination / "policy.json"
    policy_path.write_text(policy.model_dump_json(indent=2) + "\n")
    lineage_dict = asdict(context)
    lineage_dict["created_at"] = context.created_at.isoformat()
    rows = output.diagnostics
    report = dict(
        experiment_id=args.experiment_id,
        lineage=lineage_dict,
        protocol=protocol.model_dump(mode="json"),
        calibration=str(args.calibration),
        input_evidence=input_evidence,
        n_rows=len(output.values),
        n_available=int(rows.available.sum()),
        n_diagnostic=int(rows.diagnostic_alpha.notna().sum()),
        gross_mean_abs_edge_bps=float(rows.gross_edge_bps.abs().mean()),
        net_mean_abs_edge_bps=float(rows.net_edge_bps.abs().mean()),
        n_inside_cost=int(rows.net_edge_bps.eq(0).sum()),
        limitations=[
            "VALID rows predate the fitted map; actionable values are unavailable.",
            "Diagnostic values are retrospective development calculations.",
            "No ML alpha registration, trading P&L, gates or TEST access; step 145 follows.",
        ],
        artifact_hashes={
            name: sha256_file(destination / name)
            for name in ("diagnostics.parquet", "alpha_values.jsonl", "policy.json")
        },
    )
    path = destination / "metrics.json"
    with path.open("x") as handle:
        json.dump(report, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    with get_engine().begin() as connection:
        set_status(connection, args.experiment_id, ExperimentStatus.FINISHED)
    print(path)


if __name__ == "__main__":
    main()
