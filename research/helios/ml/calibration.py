"""VALID-only isotonic calibration of an existing fixed classifier (136).

Reliability on the calibration rows is a resubstitution diagnostic. The frozen
map becomes available only after VALID closes, never retroactively at those rows.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
import pandas as pd
from pydantic import Field, model_validator
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss, log_loss

from helios.common.config import HeliosConfig
from helios.common.project_config import SplitsConfig
from helios.data.binance import sha256_file
from helios.ml.dataset import HOUR_US, DatasetError
from helios.registry.results import Split
from helios.sim.splits import SplitWindow, split_window


class IsotonicMap(HeliosConfig):
    x: tuple[float, ...] = Field(min_length=2)
    y: tuple[float, ...] = Field(min_length=2)
    available_after_us: int = Field(ge=0)
    source_metrics_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_id: str = Field(min_length=8)

    @model_validator(mode="after")
    def _ordered(self) -> IsotonicMap:
        x, y = np.array(self.x), np.array(self.y)
        if (
            len(x) != len(y)
            or not np.isfinite(x).all()
            or not np.isfinite(y).all()
            or (np.diff(x) <= 0).any()
            or (np.diff(y) < 0).any()
            or (x < 0).any()
            or (x > 1).any()
            or (y < 0).any()
            or (y > 1).any()
        ):
            raise ValueError("isotonic thresholds require ordered finite probabilities")
        return self

    def probabilities(self, raw: pd.Series) -> np.ndarray[Any, np.dtype[np.float64]]:
        values = raw.to_numpy(dtype=float)
        if not np.isfinite(values).all() or ((values < 0) | (values > 1)).any():
            raise DatasetError("probabilities must be finite in [0,1]")
        result: np.ndarray[Any, np.dtype[np.float64]] = np.interp(values, self.x, self.y)
        return result


def validate_predictions(frame: pd.DataFrame, window: SplitWindow) -> None:
    required = {
        "symbol",
        "open_time",
        "label_end_time",
        "target",
        "direction_label",
        "probability_positive",
    }
    if not frame.columns.is_unique or not required.issubset(frame) or len(frame) < 2:
        raise DatasetError("calibration requires the saved prediction columns and two rows")
    for name in ("open_time", "label_end_time"):
        if (
            not pd.api.types.is_integer_dtype(frame[name])
            or pd.api.types.is_bool_dtype(frame[name])
            or frame[name].isna().any()
        ):
            raise DatasetError("prediction timestamps must be integer UTC microseconds")
    if not frame.symbol.map(lambda s: isinstance(s, str) and s.isalnum() and s.isupper()).all():
        raise DatasetError("invalid prediction symbol")
    times = frame.open_time.to_numpy(dtype=np.int64)
    ends = frame.label_end_time.to_numpy(dtype=np.int64)
    keys = list(zip(times, frame.symbol, strict=True))
    if keys != sorted(keys) or len(set(keys)) != len(keys):
        raise DatasetError("predictions must be chronological and unique by time/symbol")
    if (
        (times < window.start_us).any()
        or (ends >= window.end_us).any()
        or (times % HOUR_US != 0).any()
        or (ends - times != window.horizon_periods * HOUR_US).any()
    ):
        raise DatasetError("prediction labels cross the selected split boundary")
    target = frame.target.to_numpy(dtype=float)
    labels = frame.direction_label.to_numpy()
    raw = frame.probability_positive.to_numpy(dtype=float)
    if (
        not np.isfinite(target).all()
        or not np.array_equal(labels, (target > 0).astype(int))
        or not np.isfinite(raw).all()
        or ((raw < 0) | (raw > 1)).any()
    ):
        raise DatasetError("malformed saved probabilities or direction labels")


def reliability(
    labels: np.ndarray[Any, Any], probabilities: np.ndarray[Any, Any]
) -> dict[str, Any]:
    # Fixed equal-width bins, include probability=1 in the final bin.
    bins = np.minimum((probabilities * 10).astype(int), 9)
    curve = []
    for bucket in range(10):
        mask = bins == bucket
        if mask.any():
            curve.append(
                dict(
                    bin=bucket,
                    n=int(mask.sum()),
                    mean_probability=float(probabilities[mask].mean()),
                    observed_positive=float(labels[mask].mean()),
                )
            )
    return dict(
        brier=float(brier_score_loss(labels, probabilities)),
        log_loss=float(log_loss(labels, probabilities, labels=[0, 1])),
        curve=curve,
    )


def fit_valid_calibration(
    predictions: pd.DataFrame,
    window: SplitWindow,
    *,
    source_metrics_sha256: str,
    model_sha256: str,
    snapshot_id: str,
) -> tuple[IsotonicMap, pd.DataFrame, dict[str, Any]]:
    if window.split is not Split.VALID:
        raise DatasetError("isotonic fitting is VALID only; TRAIN/TEST are forbidden")
    if window != split_window(
        Split.VALID,
        interval=window.interval,
        horizon_periods=window.horizon_periods,
        splits=SplitsConfig.model_validate_json(window.splits_json),
    ):
        raise DatasetError("calibration requires the configured VALID window")
    validate_predictions(predictions, window)
    raw = predictions.probability_positive.to_numpy(dtype=float)
    labels = predictions.direction_label.to_numpy(dtype=int)
    if len(np.unique(raw)) < 2 or len(np.unique(labels)) != 2:
        raise DatasetError("isotonic fitting needs both labels and distinct probabilities")
    model = IsotonicRegression(increasing=True, out_of_bounds="clip").fit(raw, labels)
    frozen = IsotonicMap(
        x=tuple(model.X_thresholds_),
        y=tuple(model.y_thresholds_),
        available_after_us=window.end_us,
        source_metrics_sha256=source_metrics_sha256,
        model_sha256=model_sha256,
        snapshot_id=snapshot_id,
    )
    output = predictions.copy(deep=True)
    output["probability_calibrated"] = frozen.probabilities(predictions.probability_positive)
    report = dict(
        n_samples=len(output),
        split="valid",
        bins=10,
        method="isotonic",
        raw=reliability(labels, raw),
        calibrated=reliability(labels, output.probability_calibrated.to_numpy()),
        diagnostic="same-row VALID resubstitution; not independent performance",
        limitations=[
            "The source model already selected its iteration on VALID.",
            "No TEST access, refit of the classifier, or gate approval.",
            "The frozen map cannot authorize historical VALID decisions.",
        ],
    )
    return frozen, output, report


def verified_source(metrics_path: Path) -> tuple[dict[str, Any], pd.DataFrame]:
    report: dict[str, Any] = json.loads(metrics_path.read_text())
    if report["protocol"]["version"] != "hourly_lightgbm_v1":
        raise DatasetError("calibration source must be the fixed LightGBM run")
    for name in ("lightgbm.joblib", "valid_predictions.parquet"):
        if sha256_file(metrics_path.parent / name) != report["artifact_hashes"][name]:
            raise DatasetError("source artifact hash mismatch")
    if report["lineage"]["dirty"] or report["protocol"]["test_access"]:
        raise DatasetError("source must have clean TRAIN/VALID lineage")
    return report, pd.read_parquet(metrics_path.parent / "valid_predictions.parquet")


def save_calibration(
    frozen: IsotonicMap, predictions: pd.DataFrame, report: dict[str, Any], output_dir: Path
) -> Path:
    destination = output_dir / str(uuid4())
    destination.mkdir(parents=True, exist_ok=False)
    map_path = destination / "isotonic.json"
    map_path.write_text(frozen.model_dump_json(indent=2) + "\n")
    frame_path = destination / "valid_diagnostics.parquet"
    predictions.to_parquet(frame_path, index=False)
    # Plotting is an artifact-generation dependency (the existing notebooks group).
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6, 5))
    ax.plot([0, 1], [0, 1], "--", color="gray", label="Perfect calibration")
    for key in ("raw", "calibrated"):
        curve = report[key]["curve"]
        ax.plot(
            [p["mean_probability"] for p in curve],
            [p["observed_positive"] for p in curve],
            "o-",
            label=key,
        )
    ax.set(
        xlim=(0, 1),
        ylim=(0, 1),
        xlabel="Mean predicted probability",
        ylabel="Observed positive fraction",
        title="VALID resubstitution diagnostic",
    )
    ax.legend()
    fig.tight_layout()
    fig.savefig(destination / "calibration.svg")
    plt.close(fig)
    report = report | dict(
        map=frozen.model_dump(mode="json"),
        artifact_hashes={
            name: sha256_file(destination / name)
            for name in ("isotonic.json", "valid_diagnostics.parquet", "calibration.svg")
        },
    )
    path = destination / "metrics.json"
    with path.open("x") as handle:
        handle.write(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return path
