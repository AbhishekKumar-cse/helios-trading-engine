"""Simple, honest baselines on the FI-2010 benchmark (steps 050, 063).

A baseline answers "how hard is this problem?" before any deep model is built. If a fancy
model cannot beat logistic regression, the fancy model is not earning its keep.

**Why macro-F1 and not accuracy.** At horizon k = 10 about 60 % of FI-2010 labels are
"stationary", so a model that always predicts "stationary" scores ~60 % accuracy while being
useless. Macro-F1 averages the score of the three classes equally, so that trick scores
badly. Both numbers are reported, together with the always-predict-the-commonest-class score,
so a result can never look good by accident.

**Why seeds.** Logistic regression here is deterministic, so its three seeds must give
identical numbers: that is a check for hidden randomness. A neural network starts from random
weights, so its seeds give genuinely different numbers, and the spread across them is part of
the result — a single lucky run means nothing.
"""

from __future__ import annotations

import time
from collections.abc import Sequence

import numpy as np
import pandas as pd
from pydantic import Field
from sklearn.base import BaseEstimator
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from helios.common.config import HeliosConfig, config_hash
from helios.common.lineage import RunContext
from helios.common.seed import set_seed
from helios.ml.fi2010 import LABEL_HORIZONS, FI2010Error, FI2010Split

RESULT_COLUMNS = (
    "model",
    "horizon",
    "seed",
    "n_train",
    "n_test",
    "accuracy",
    "macro_f1",
    "majority_accuracy",
    "fit_seconds",
    "code_commit",
    "dirty",
    "config_hash",
    "created_at",
)

DEFAULT_SNAPSHOT = "fi2010-deeplob-2021-07-14"


class BaselineConfig(HeliosConfig):
    """Settings shared by every baseline: they decide the result, so they are hashed."""

    model: str
    features: str = "lob_40"
    horizon: int = 10
    val_fraction: float = 0.2
    standardise: bool = True


class LogisticBaselineConfig(BaselineConfig):
    """Multinomial logistic regression (step 050)."""

    model: str = "logistic_regression"
    max_iter: int = Field(default=200, gt=0)
    C: float = Field(default=1.0, gt=0)


class MLPBaselineConfig(BaselineConfig):
    """A small neural network (step 063).

    `early_stopping` stays **off** on purpose: scikit-learn would carve its own validation
    slice out of the training data by shuffling, which mixes later events into an earlier
    period. The number of passes is fixed instead, and reported.
    """

    model: str = "mlp"
    hidden_layer_sizes: tuple[int, ...] = (64,)
    max_iter: int = Field(default=30, gt=0)
    alpha: float = Field(default=1e-4, ge=0)
    learning_rate_init: float = Field(default=1e-3, gt=0)
    batch_size: int = Field(default=256, gt=0)


def majority_accuracy(train_labels: np.ndarray, test_labels: np.ndarray) -> float:
    """Score of always predicting the class that is commonest in the training data."""
    commonest = np.bincount(train_labels).argmax()
    return float((test_labels == commonest).mean())


def _build(config: BaselineConfig, seed: int) -> Pipeline:
    """The model for one seed, with standardising in front when asked."""
    estimator: BaseEstimator
    if isinstance(config, LogisticBaselineConfig):
        estimator = LogisticRegression(max_iter=config.max_iter, C=config.C, random_state=seed)
    elif isinstance(config, MLPBaselineConfig):
        estimator = MLPClassifier(
            hidden_layer_sizes=config.hidden_layer_sizes,
            max_iter=config.max_iter,
            alpha=config.alpha,
            learning_rate_init=config.learning_rate_init,
            batch_size=config.batch_size,
            early_stopping=False,
            random_state=seed,
        )
    else:
        raise FI2010Error(f"no model is defined for {type(config).__name__}")

    steps: list[tuple[str, BaseEstimator]] = []
    if config.standardise:
        steps.append(("scale", StandardScaler()))
    steps.append((config.model, estimator))
    return Pipeline(steps)


def run_baseline(
    split: FI2010Split,
    config: BaselineConfig,
    seeds: Sequence[int] = (0, 1, 2),
    data_snapshot_id: str = DEFAULT_SNAPSHOT,
) -> pd.DataFrame:
    """Train one model per seed and return a row of measurements for each."""
    if config.horizon not in LABEL_HORIZONS:
        raise FI2010Error(f"horizon must be one of {LABEL_HORIZONS}, got {config.horizon}")
    if not seeds:
        raise FI2010Error("give at least one seed")

    x_train, y_train = split.train.lob, split.train.labels_for(config.horizon)
    x_test, y_test = split.test.lob, split.test.labels_for(config.horizon)
    fingerprint = config_hash(config)

    rows = []
    for seed in seeds:
        set_seed(seed)
        lineage = RunContext.capture(config, data_snapshot_id, seed)
        model = _build(config, seed)

        started = time.perf_counter()
        model.fit(x_train, y_train)
        fit_seconds = time.perf_counter() - started

        predicted = model.predict(x_test)
        rows.append(
            {
                "model": config.model,
                "horizon": config.horizon,
                "seed": seed,
                "n_train": len(y_train),
                "n_test": len(y_test),
                "accuracy": float(accuracy_score(y_test, predicted)),
                "macro_f1": float(f1_score(y_test, predicted, average="macro")),
                "majority_accuracy": majority_accuracy(y_train, y_test),
                "fit_seconds": round(fit_seconds, 2),
                "code_commit": lineage.code_commit,
                "dirty": lineage.dirty,
                "config_hash": fingerprint,
                "created_at": lineage.created_at.isoformat(),
            }
        )
    return pd.DataFrame(rows, columns=list(RESULT_COLUMNS))


def run_logistic_baseline(
    split: FI2010Split,
    config: LogisticBaselineConfig | None = None,
    seeds: Sequence[int] = (0, 1, 2),
    data_snapshot_id: str = DEFAULT_SNAPSHOT,
) -> pd.DataFrame:
    """Baseline 1 (step 050). Deterministic: every seed must give the same numbers."""
    return run_baseline(split, config or LogisticBaselineConfig(), seeds, data_snapshot_id)


def run_mlp_baseline(
    split: FI2010Split,
    config: MLPBaselineConfig | None = None,
    seeds: Sequence[int] = (0, 1, 2),
    data_snapshot_id: str = DEFAULT_SNAPSHOT,
) -> pd.DataFrame:
    """Baseline 2 (step 063). Random starting weights, so the seeds really do differ."""
    return run_baseline(split, config or MLPBaselineConfig(), seeds, data_snapshot_id)


def summarise(results: pd.DataFrame) -> pd.DataFrame:
    """Mean and standard deviation across seeds, per model and horizon.

    The spread matters as much as the average: a model whose macro-F1 swings by 0.1 between
    seeds has not really achieved its best run.
    """
    if results.empty:
        raise FI2010Error("no results to summarise")
    grouped = results.groupby(["model", "horizon"], as_index=False).agg(
        seeds=("seed", "count"),
        accuracy_mean=("accuracy", "mean"),
        accuracy_std=("accuracy", "std"),
        macro_f1_mean=("macro_f1", "mean"),
        macro_f1_std=("macro_f1", "std"),
        majority_accuracy=("majority_accuracy", "first"),
        fit_seconds_mean=("fit_seconds", "mean"),
    )
    # one seed has no spread; report 0 rather than an empty cell
    return grouped.fillna({"accuracy_std": 0.0, "macro_f1_std": 0.0})
