"""Tests for the FI-2010 baselines (step 050).

These run on tiny made-up data, so they are fast and need no dataset. The real numbers come
from `scripts/fi2010_baseline.py`.
"""

import numpy as np
import pytest

from helios.ml.baselines import (
    RESULT_COLUMNS,
    LogisticBaselineConfig,
    majority_accuracy,
    run_logistic_baseline,
)
from helios.ml.fi2010 import FI2010Data, FI2010Error, FI2010Split


def toy_part(n: int, seed: int = 0) -> FI2010Data:
    """Order-book columns that actually carry a signal, so the model can learn something."""
    rng = np.random.default_rng(seed)
    labels = rng.integers(1, 4, size=(n, 5)).astype(np.int8)
    lob = rng.normal(size=(n, 40))
    lob[:, 0] += labels[:, 0] * 3.0  # first column tells you the k=10 label
    return FI2010Data(lob=lob, features=rng.normal(size=(n, 104)), labels=labels)


def toy_split(n: int = 300) -> FI2010Split:
    return FI2010Split(train=toy_part(n, 0), val=toy_part(n // 4, 1), test=toy_part(n // 2, 2))


def test_one_row_per_seed_with_all_columns() -> None:
    results = run_logistic_baseline(toy_split(), seeds=(0, 1, 2))
    assert list(results.columns) == list(RESULT_COLUMNS)
    assert results["seed"].tolist() == [0, 1, 2]


def test_scores_are_in_range_and_beat_guessing() -> None:
    results = run_logistic_baseline(toy_split(), seeds=(0,))
    row = results.iloc[0]
    assert 0.0 <= row["accuracy"] <= 1.0
    assert 0.0 <= row["macro_f1"] <= 1.0
    assert row["accuracy"] > row["majority_accuracy"]  # the signal is learnable


def test_seeds_give_the_same_answer() -> None:
    """This solver is deterministic: equal numbers prove no hidden randomness."""
    results = run_logistic_baseline(toy_split(), seeds=(0, 1, 2))
    assert results["accuracy"].nunique() == 1
    assert results["macro_f1"].nunique() == 1


def test_lineage_is_recorded() -> None:
    row = run_logistic_baseline(toy_split(), seeds=(0,)).iloc[0]
    assert len(row["code_commit"]) == 40  # the git commit the result came from
    assert isinstance(bool(row["dirty"]), bool)
    assert len(row["config_hash"]) == 64
    assert row["created_at"].endswith("+00:00")


def test_same_config_gives_the_same_hash() -> None:
    a = run_logistic_baseline(toy_split(), seeds=(0,))
    b = run_logistic_baseline(toy_split(), seeds=(0,))
    assert a["config_hash"].iloc[0] == b["config_hash"].iloc[0]


def test_different_config_gives_a_different_hash() -> None:
    a = run_logistic_baseline(toy_split(), LogisticBaselineConfig(horizon=10), seeds=(0,))
    b = run_logistic_baseline(toy_split(), LogisticBaselineConfig(horizon=50), seeds=(0,))
    assert a["config_hash"].iloc[0] != b["config_hash"].iloc[0]


def test_majority_accuracy() -> None:
    train = np.array([1, 1, 1, 2, 3])  # class 1 is commonest
    test = np.array([1, 1, 2, 3])
    assert majority_accuracy(train, test) == pytest.approx(0.5)


def test_bad_horizon_is_rejected() -> None:
    with pytest.raises(FI2010Error, match="horizon must be one of"):
        run_logistic_baseline(toy_split(), LogisticBaselineConfig(horizon=7), seeds=(0,))


def test_no_seeds_is_rejected() -> None:
    with pytest.raises(FI2010Error, match="at least one seed"):
        run_logistic_baseline(toy_split(), seeds=())
