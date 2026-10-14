"""Fixed hourly ridge/logistic TRAIN fits and VALID predictive metrics (125)."""

from __future__ import annotations

import hashlib
import json
import warnings
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import joblib  # type: ignore[import-untyped]
import numpy as np
import pandas as pd
from pydantic import Field, StrictInt, model_validator
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    log_loss,
    mean_absolute_error,
    mean_squared_error,
    r2_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from helios.common.config import HeliosConfig
from helios.common.lineage import RunContext
from helios.common.project_config import load_splits
from helios.data.binance import sha256_file
from helios.ml.dataset import DatasetConfig, DatasetError
from helios.ml.splits import SplitDataset, dataset_for_split
from helios.registry.results import Split

FEATURES = (
    "log_return_1",
    "log_return_4",
    "log_return_24",
    "volatility_24",
    "volume_zscore_168",
    "taker_buy_ratio",
    "hour_of_day_sin",
    "hour_of_day_cos",
)


class HourlyBaselineConfig(HeliosConfig):
    dataset: DatasetConfig = Field(default_factory=lambda: DatasetConfig(features=FEATURES))
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
    seed: StrictInt = Field(default=0, ge=0, le=2**32 - 1)
    ridge_alpha: float = Field(default=1.0, gt=0, allow_inf_nan=False)
    logistic_c: float = Field(default=1.0, gt=0, allow_inf_nan=False)
    max_iter: StrictInt = Field(default=1000, ge=1)
    tolerance: float = Field(default=1e-6, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def _universe(self) -> HourlyBaselineConfig:
        if not self.symbols or len(set(self.symbols)) != len(self.symbols):
            raise ValueError("baseline requires a unique nonempty symbol universe")
        if any(not s.isalnum() or not s.isupper() for s in self.symbols):
            raise ValueError("invalid baseline symbol")
        return self


def fixed_protocol(config: HourlyBaselineConfig) -> dict[str, Any]:
    return dict(
        version="hourly_linear_v1",
        config=config.model_dump(mode="json"),
        splits=load_splits().model_dump(mode="json"),
        train="TRAIN",
        evaluate="VALID",
        classifier_label="forward_return_gt_zero_v1",
        scaler="StandardScaler fitted on TRAIN only",
        row_policy=(
            "complete on-grid bars only; paired available features and contiguous labels; "
            "explicit exclusions, no filling"
        ),
        test_access=False,
        tune=False,
    )


@dataclass
class BaselineRun:
    report: dict[str, Any]
    models: dict[str, Pipeline]
    predictions: pd.DataFrame


def _validate_pair(train: SplitDataset, valid: SplitDataset, config: HourlyBaselineConfig) -> None:
    if train.window.split is not Split.TRAIN or valid.window.split is not Split.VALID:
        raise DatasetError("baseline fits TRAIN and scores VALID only; TEST is forbidden")
    if (
        train.dataset.config != config.dataset
        or valid.dataset.config != config.dataset
        or train.dataset.snapshot_id is None
        or train.dataset.snapshot_id != valid.dataset.snapshot_id
        or train.window.splits_json != valid.window.splits_json
    ):
        raise DatasetError("baseline config, snapshot or split mismatch")
    for part in (train, valid):
        samples = part.dataset.samples
        if len(samples) < 2:
            raise DatasetError("baseline requires at least two usable samples per split")
        if dataset_for_split(part.dataset, part.window).dataset.samples != samples:
            raise DatasetError("samples cross split boundaries")
        keys = [(s.open_time, s.symbol) for s in samples]
        if keys != sorted(keys) or len(set(keys)) != len(keys):
            raise DatasetError("baseline samples must be unique and chronological")
        if not set(s.symbol for s in samples).issubset(config.symbols):
            raise DatasetError("baseline samples contain an undeclared symbol")
        if not np.isfinite(part.dataset.X).all() or not np.isfinite(part.dataset.y).all():
            raise DatasetError("baseline samples must be finite and available")
    if max(s.label_end_time for s in train.dataset.samples) >= valid.window.start_us:
        raise DatasetError("TRAIN labels overlap VALID")
    if len(np.unique(train.dataset.y > 0)) != 2:
        raise DatasetError("logistic training requires both direction classes")


def fit_hourly_baselines(
    train: SplitDataset,
    valid: SplitDataset,
    config: HourlyBaselineConfig | None = None,
    *,
    reported: bool = True,
) -> BaselineRun:
    selected = HourlyBaselineConfig() if config is None else config
    selected = HourlyBaselineConfig.model_validate(selected.model_dump())
    _validate_pair(train, valid, selected)
    snapshot = train.dataset.snapshot_id
    assert snapshot is not None
    context = RunContext.capture(selected, snapshot, selected.seed, reported=reported)
    x_train, y_train = train.dataset.X, train.dataset.y
    x_valid, y_valid = valid.dataset.X, valid.dataset.y
    labels_train, labels_valid = (y_train > 0).astype(int), (y_valid > 0).astype(int)
    models = {
        "ridge": Pipeline(
            [
                ("scale", StandardScaler()),
                (
                    "model",
                    Ridge(
                        alpha=selected.ridge_alpha,
                        solver="lsqr",
                        tol=selected.tolerance,
                        max_iter=selected.max_iter,
                    ),
                ),
            ]
        ),
        "logistic": Pipeline(
            [
                ("scale", StandardScaler()),
                (
                    "model",
                    LogisticRegression(
                        C=selected.logistic_c,
                        random_state=selected.seed,
                        solver="lbfgs",
                        tol=selected.tolerance,
                        max_iter=selected.max_iter,
                    ),
                ),
            ]
        ),
    }
    convergence: dict[str, bool] = {}
    for name, model in models.items():
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ConvergenceWarning)
            model.fit(x_train, y_train if name == "ridge" else labels_train)
        convergence[name] = not any(issubclass(w.category, ConvergenceWarning) for w in caught)
    ridge = models["ridge"].predict(x_valid)
    direction = models["logistic"].predict(x_valid)
    probability = models["logistic"].predict_proba(x_valid)[:, 1]
    majority = int(np.bincount(labels_train, minlength=2).argmax())
    constant_direction = np.full(len(labels_valid), majority)
    constant_return = np.full(len(y_valid), float(y_train.mean()))
    evidence: dict[str, Any] = {}
    for name, part in (("TRAIN", train), ("VALID", valid)):
        digest = hashlib.sha256()
        for sample in part.dataset.samples:
            digest.update(json.dumps(asdict(sample), sort_keys=True, allow_nan=False).encode())
        evidence[name] = dict(
            n_samples=len(part.dataset.samples),
            sample_sha256=digest.hexdigest(),
            input_hashes=dict(part.dataset.input_hashes),
            availability=[asdict(c) for c in part.dataset.counts],
            n_purged_labels=part.n_purged_labels,
            n_outside_split=part.n_outside_split,
            first_open_time=part.dataset.samples[0].open_time,
            last_label_end_time=max(s.label_end_time for s in part.dataset.samples),
        )
    lineage = asdict(context)
    lineage["created_at"] = context.created_at.isoformat()
    report = dict(
        protocol=fixed_protocol(selected) | {"splits": json.loads(train.window.splits_json)},
        lineage=lineage,
        datasets=evidence,
        convergence=convergence,
        ridge=dict(
            mae=float(mean_absolute_error(y_valid, ridge)),
            rmse=float(np.sqrt(mean_squared_error(y_valid, ridge))),
            r2=float(r2_score(y_valid, ridge)) if np.var(y_valid) > 0 else None,
            train_mean_rmse=float(np.sqrt(mean_squared_error(y_valid, constant_return))),
        ),
        logistic=dict(
            accuracy=float(accuracy_score(labels_valid, direction)),
            macro_f1=float(
                f1_score(labels_valid, direction, labels=[0, 1], average="macro", zero_division=0)
            ),
            log_loss=float(log_loss(labels_valid, probability, labels=[0, 1])),
            roc_auc=float(roc_auc_score(labels_valid, probability))
            if len(np.unique(labels_valid)) == 2
            else None,
            majority_accuracy=float(accuracy_score(labels_valid, constant_direction)),
            majority_macro_f1=float(
                f1_score(
                    labels_valid,
                    constant_direction,
                    labels=[0, 1],
                    average="macro",
                    zero_division=0,
                )
            ),
            train_class_counts=np.bincount(labels_train, minlength=2).tolist(),
            valid_class_counts=np.bincount(labels_valid, minlength=2).tolist(),
        ),
        scaler_mean={
            name: model.named_steps["scale"].mean_.tolist() for name, model in models.items()
        },
        limitations=[
            "Predictive VALID metrics only, not net trading P&L or gate approval.",
            "Unavailable/irregular observations are explicitly excluded; no rows filled.",
            "One fixed seed/config, no tuning and no TEST access.",
        ],
    )
    predictions = pd.DataFrame(
        dict(
            symbol=[s.symbol for s in valid.dataset.samples],
            open_time=[s.open_time for s in valid.dataset.samples],
            label_end_time=[s.label_end_time for s in valid.dataset.samples],
            target=y_valid,
            ridge_return=ridge,
            direction_label=labels_valid,
            direction_predicted=direction,
            probability_positive=probability,
        )
    )
    return BaselineRun(report, models, predictions)


def save_baseline_run(run: BaselineRun, output_dir: Path) -> Path:
    """Fresh UUID directory; no metric/checkpoint replacement or best-run selection."""
    destination = output_dir / str(uuid4())
    destination.mkdir(parents=True, exist_ok=False)
    artifact_hashes = {}
    for name, model in run.models.items():
        path = destination / f"{name}.joblib"
        joblib.dump(model, path)
        artifact_hashes[path.name] = sha256_file(path)
    path = destination / "valid_predictions.parquet"
    run.predictions.to_parquet(path, index=False)
    artifact_hashes[path.name] = sha256_file(path)
    report = run.report | dict(artifact_hashes=artifact_hashes)
    with (destination / "metrics.json").open("x") as handle:
        handle.write(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
        handle.write("\n")
    return destination / "metrics.json"
