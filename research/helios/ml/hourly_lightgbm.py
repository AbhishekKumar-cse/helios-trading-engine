"""Fixed LightGBM direction baseline; VALID selects stopping iteration (126)."""

import hashlib
import json
from dataclasses import asdict

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier, early_stopping
from pydantic import Field, StrictInt
from sklearn.metrics import accuracy_score, f1_score, log_loss, roc_auc_score
from sklearn.pipeline import Pipeline

from helios.common.lineage import RunContext
from helios.ml.hourly_baselines import (
    BaselineRun,
    HourlyBaselineConfig,
    _validate_pair,
    fixed_protocol,
)
from helios.ml.splits import SplitDataset


class LightGBMConfig(HourlyBaselineConfig):
    n_estimators: StrictInt = Field(default=500, ge=2)
    num_leaves: StrictInt = Field(default=31, ge=2)
    min_child_samples: StrictInt = Field(default=100, ge=1)
    stopping_rounds: StrictInt = Field(default=50, ge=1)
    learning_rate: float = Field(default=0.05, gt=0, le=1, allow_inf_nan=False)


def lightgbm_protocol(config: LightGBMConfig) -> dict[str, object]:
    protocol = fixed_protocol(config)
    protocol.update(
        version="minute_lightgbm_v1" if config.dataset.interval == "1m" else "hourly_lightgbm_v1",
        scaler="none; tree inputs retain original units",
        selection="fixed binary-logloss early stopping on VALID; VALID is not an independent test",
        deterministic=True,
        force_col_wise=True,
        n_jobs=2,
    )
    return protocol


def fit_lightgbm(
    train: SplitDataset, valid: SplitDataset, config: LightGBMConfig, *, reported: bool = True
) -> BaselineRun:
    config = LightGBMConfig.model_validate(config.model_dump())
    _validate_pair(train, valid, config)
    assert train.dataset.snapshot_id is not None
    context = RunContext.capture(config, train.dataset.snapshot_id, config.seed, reported=reported)
    labels_train = (train.dataset.y > 0).astype(int)
    labels_valid = (valid.dataset.y > 0).astype(int)
    model = LGBMClassifier(
        objective="binary",
        metric="binary_logloss",
        n_estimators=config.n_estimators,
        num_leaves=config.num_leaves,
        min_child_samples=config.min_child_samples,
        learning_rate=config.learning_rate,
        reg_lambda=1.0,
        random_state=config.seed,
        n_jobs=2,
        verbosity=-1,
        deterministic=True,
        force_col_wise=True,
        data_random_seed=config.seed,
        feature_fraction_seed=config.seed,
        bagging_seed=config.seed,
    )
    model.fit(
        train.dataset.X,
        labels_train,
        eval_X=valid.dataset.X,
        eval_y=labels_valid,
        eval_metric="binary_logloss",
        callbacks=[early_stopping(config.stopping_rounds, first_metric_only=True, verbose=False)],
    )
    probability = np.asarray(model.predict_proba(valid.dataset.X), dtype=float)[:, 1]
    predicted = (probability >= 0.5).astype(int)
    majority = np.full(len(labels_valid), np.bincount(labels_train, minlength=2).argmax())
    lineage = asdict(context)
    lineage["created_at"] = context.created_at.isoformat()
    report = dict(
        protocol=lightgbm_protocol(config),
        lineage=lineage,
        best_iteration=int(model.best_iteration_),
        metrics=dict(
            accuracy=float(accuracy_score(labels_valid, predicted)),
            macro_f1=float(
                f1_score(labels_valid, predicted, labels=[0, 1], average="macro", zero_division=0)
            ),
            log_loss=float(log_loss(labels_valid, probability, labels=[0, 1])),
            roc_auc=float(roc_auc_score(labels_valid, probability))
            if len(np.unique(labels_valid)) == 2
            else None,
            majority_accuracy=float(accuracy_score(labels_valid, majority)),
        ),
        datasets={
            name: dict(
                n_samples=len(part.dataset.samples),
                sample_sha256=hashlib.sha256(
                    json.dumps([asdict(s) for s in part.dataset.samples], sort_keys=True).encode()
                ).hexdigest(),
                input_hashes=dict(part.dataset.input_hashes),
                availability=[asdict(c) for c in part.dataset.counts],
                n_purged_labels=part.n_purged_labels,
            )
            for name, part in (("TRAIN", train), ("VALID", valid))
        },
        limitations=[
            "VALID selected the stopping iteration; this is development evidence.",
            "No TEST access, parameter search, calibration, trading P&L or promotion.",
        ],
    )
    predictions = pd.DataFrame(
        dict(
            symbol=[s.symbol for s in valid.dataset.samples],
            open_time=[s.open_time for s in valid.dataset.samples],
            label_end_time=[s.label_end_time for s in valid.dataset.samples],
            target=valid.dataset.y,
            direction_label=labels_valid,
            direction_predicted=predicted,
            probability_positive=probability,
        )
    )
    return BaselineRun(report, {"lightgbm": Pipeline([("model", model)])}, predictions)
