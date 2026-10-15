"""Hash-anchored, frozen ML signals for the common simulator; no fitting (145)."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from helios.alpha.definition import AlphaDefinition, AlphaProvenance
from helios.alpha.output import BoundedAlphaSeries
from helios.common.config import config_hash
from helios.common.project_config import HorizonFamily, load_fees, load_gates, load_splits
from helios.common.types import AlphaStatus, AlphaValue
from helios.data.binance import sha256_file
from helios.ml.calibration import IsotonicMap, verified_source
from helios.ml.dataset import HOUR_US, DatasetConfig, DatasetError
from helios.ml.prediction_alpha import MLAlphaPolicy, prediction_to_alpha
from helios.registry.results import Split
from helios.sim.splits import SplitWindow, split_window


@dataclass(frozen=True)
class FrozenMLArtifact:
    path: Path
    model_ref: str
    report: dict[str, Any]
    policy: MLAlphaPolicy
    dataset: DatasetConfig
    values: tuple[AlphaValue, ...]


def _children(path: Path, report: dict[str, Any], names: tuple[str, ...]) -> None:
    for name in names:
        if sha256_file(path.parent / name) != report["artifact_hashes"][name]:
            raise DatasetError("frozen ML artifact checksum mismatch")


def read_frozen_ml(path: Path, model_ref: str | None = None) -> FrozenMLArtifact:
    digest = "sha256:" + sha256_file(path)
    if model_ref is not None and digest != model_ref:
        raise DatasetError("registered ML model reference checksum mismatch")
    report = json.loads(path.read_text())
    _children(path, report, ("policy.json", "alpha_values.jsonl", "diagnostics.parquet"))
    policy = MLAlphaPolicy.model_validate_json((path.parent / "policy.json").read_text())
    calibration_path = Path(report["calibration"])
    if sha256_file(calibration_path) != report["protocol"]["calibration_metrics_sha256"]:
        raise DatasetError("frozen calibration metrics checksum mismatch")
    calibration = json.loads(calibration_path.read_text())
    _children(
        calibration_path,
        calibration,
        ("isotonic.json", "valid_diagnostics.parquet", "calibration.svg"),
    )
    frozen = IsotonicMap.model_validate_json(
        (calibration_path.parent / "isotonic.json").read_text()
    )
    source_path = Path(calibration["source"])
    if (
        frozen != policy.calibration
        or calibration["map"] != frozen.model_dump(mode="json")
        or sha256_file(source_path) != frozen.source_metrics_sha256
    ):
        raise DatasetError("frozen policy/calibration/source lineage mismatch")
    source, predictions = verified_source(source_path)
    dataset = DatasetConfig.model_validate(source["protocol"]["config"]["dataset"])
    if source["artifact_hashes"]["lightgbm.joblib"] != frozen.model_sha256:
        raise DatasetError("frozen classifier hash mismatch")
    for evidence in (report, calibration, source):
        if (
            evidence["lineage"]["dirty"] is not False
            or evidence["lineage"]["data_snapshot_id"] != frozen.snapshot_id
            or evidence["protocol"]["test_access"] is not False
        ):
            raise DatasetError("frozen ML requires clean matching TRAIN/VALID lineage")
    if (
        report["lineage"]["config_hash"] != config_hash(policy)
        or config_hash(policy.fees) != config_hash(load_fees())
        or frozen.available_after_us < split_window(Split.VALID, interval="1h").end_us
        or policy.payoffs.available_after_us < split_window(Split.TRAIN, interval="1h").end_us
        or report["protocol"]["post_calibration_only"] is not True
        or report["protocol"]["window"] != policy.window
        or report["protocol"]["cost_sides"] != policy.cost_sides
    ):
        raise DatasetError("frozen ML policy, costs or fit availability mismatch")
    with (path.parent / "alpha_values.jsonl").open() as handle:
        values = tuple(AlphaValue.model_validate_json(line) for line in handle)
    if not values or len(values) != report["n_rows"]:
        raise DatasetError("frozen ML signal count mismatch")
    lineage = values[0].lineage
    if (
        lineage.code_commit != report["lineage"]["code_commit"]
        or lineage.seed != report["lineage"]["seed"]
        or lineage.feature_set_version != dataset.feature_set_version
        or lineage.horizon_family is not HorizonFamily.HOURLY
        or any(value.lineage != lineage for value in values)
    ):
        raise DatasetError("frozen ML typed signal lineage mismatch")
    # Verify the frozen transform, without refitting or using retrospective scores.
    recomputed = prediction_to_alpha(predictions, policy, lineage)
    if values != recomputed.values or report["n_available"] != sum(
        v.status is AlphaStatus.OK for v in values
    ):
        raise DatasetError("typed ML values differ from the frozen causal transform")
    return FrozenMLArtifact(path, digest, report, policy, dataset, values)


def frozen_definition(artifact: FrozenMLArtifact) -> AlphaDefinition:
    lineage = artifact.values[0].lineage
    return AlphaDefinition(
        alpha_id=lineage.alpha_id,
        version=lineage.alpha_version,
        name="Frozen calibrated hourly LightGBM alpha",
        provenance=AlphaProvenance.ML,
        feature_set_version=artifact.dataset.feature_set_version,
        horizon_family=HorizonFamily.HOURLY,
        horizon_periods=artifact.dataset.horizon,
        model_ref=artifact.model_ref,
        params={
            "artifact_path": str(artifact.path),
            "policy_hash": config_hash(artifact.policy),
            "model_sha256": artifact.policy.calibration.model_sha256,
            "transform_commit": lineage.code_commit,
        },
        author="helios_step145",
    )


def frozen_ml_series(
    definition: AlphaDefinition, window: SplitWindow, *, symbol: str, snapshot_id: str
) -> tuple[BoundedAlphaSeries, dict[str, Any]]:
    if definition.provenance is not AlphaProvenance.ML or definition.model_ref is None:
        raise DatasetError("frozen ML loader requires a registered ML model reference")
    if window.split is Split.TRAIN:
        raise DatasetError("VALID-calibrated ML artifacts cannot be loaded for TRAIN evaluation")
    path = definition.params.get("artifact_path")
    if not isinstance(path, str):
        raise DatasetError("registered ML artifact path missing")
    artifact = read_frozen_ml(Path(path), definition.model_ref)
    expected = frozen_definition(artifact)
    if (
        definition.alpha_id != expected.alpha_id
        or definition.version != expected.version
        or definition.params != expected.params
        or definition.feature_set_version != expected.feature_set_version
        or definition.horizon_periods != artifact.dataset.horizon
        or snapshot_id != artifact.policy.calibration.snapshot_id
        or window.family is not HorizonFamily.HOURLY
    ):
        raise DatasetError("registered ML definition/snapshot does not match frozen signals")
    selected = [
        v
        for v in artifact.values
        if v.symbol == symbol and window.start_us <= v.timestamp - HOUR_US < window.end_us
    ]
    alpha = BoundedAlphaSeries(
        symbol,
        pd.Series([v.timestamp - HOUR_US for v in selected], dtype="int64"),
        pd.Series([float("nan") if v.value is None else v.value for v in selected], dtype=float),
        pd.Series([v.status is AlphaStatus.OK for v in selected], dtype=bool),
        definition.output,
    )
    return alpha, dict(
        model_ref=artifact.model_ref,
        policy_hash=config_hash(artifact.policy),
        model_sha256=artifact.policy.calibration.model_sha256,
        transform_lineage=artifact.report["lineage"],
        calibration_available_after_us=artifact.policy.calibration.available_after_us,
        selected_rows=len(selected),
        available_rows=int(alpha.available.sum()),
        timestamp_mapping=(
            "typed close decision time minus one hour to originating bar; common lag=1"
        ),
    )


def ml_evaluation_protocol(artifact: FrozenMLArtifact) -> dict[str, Any]:
    return dict(
        version="frozen_hourly_ml_evaluation_v1",
        alpha_id=artifact.values[0].lineage.alpha_id,
        alpha_version=artifact.values[0].lineage.alpha_version,
        metrics_path=str(artifact.path),
        model_ref=artifact.model_ref,
        split="valid",
        symbols=sorted(artifact.policy.payoffs.means_bps),
        warmup_rows=168,
        min_periods=2,
        seed=0,
        fees_hash=config_hash(load_fees()),
        gates_hash=config_hash(load_gates()),
        splits_hash=config_hash(load_splits()),
        test_access=False,
        availability="frozen typed AlphaValue status; no retrospective diagnostic substitution",
        model_fit="unchanged existing classifier, calibration and TRAIN payoff artifacts",
    )
