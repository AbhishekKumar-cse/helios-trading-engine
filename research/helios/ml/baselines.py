"""Simple, honest baselines on the FI-2010 benchmark (step 050).

A baseline answers "how hard is this problem?" before any deep model is built. If a fancy
model cannot beat logistic regression, the fancy model is not earning its keep.

**Why macro-F1 and not accuracy.** At horizon k = 10 about 60 % of FI-2010 labels are
"stationary", so a model that always predicts "stationary" scores ~60 % accuracy while being
useless. Macro-F1 averages the score of the three classes equally, so that trick scores
badly. Both numbers are reported, together with the always-predict-the-commonest-class score,
so a result can never look good by accident.
"""

from __future__ import annotations

import time
from collections.abc import Sequence

import numpy as np
import pandas as pd
from pydantic import Field
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score
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


class LogisticBaselineConfig(HeliosConfig):
    """Everything that decides the result, so it can be hashed and repeated."""

    model: str = "logistic_regression"
    features: str = "lob_40"
    horizon: int = 10
    val_fraction: float = 0.2
    max_iter: int = Field(default=200, gt=0)
    C: float = Field(default=1.0, gt=0)
    standardise: bool = True


def majority_accuracy(train_labels: np.ndarray, test_labels: np.ndarray) -> float:
    """Score of always predicting the class that is commonest in the training data."""
    commonest = np.bincount(train_labels).argmax()
    return float((test_labels == commonest).mean())


def run_logistic_baseline(
    split: FI2010Split,
    config: LogisticBaselineConfig | None = None,
    seeds: Sequence[int] = (0, 1, 2),
    data_snapshot_id: str = "fi2010-deeplob-2021-07-14",
) -> pd.DataFrame:
    """Train logistic regression on the 40 order-book columns, once per seed.

    Returns one row per seed with accuracy, macro-F1 and the lineage of the run. Note that
    this solver is deterministic, so every seed is expected to give the *same* numbers: the
    seeds prove there is no hidden randomness, they do not measure model variance.
    """
    config = config or LogisticBaselineConfig()
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

        steps = []
        if config.standardise:
            steps.append(("scale", StandardScaler()))
        steps.append(
            (
                "logistic",
                LogisticRegression(max_iter=config.max_iter, C=config.C, random_state=seed),
            )
        )
        model = Pipeline(steps)

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
