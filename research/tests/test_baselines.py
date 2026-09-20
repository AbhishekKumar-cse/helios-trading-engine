"""Tests for the FI-2010 baselines (steps 050, 063).

These run on tiny made-up data, so they are fast and need no dataset. The real numbers come
from `scripts/fi2010_baseline.py`.
"""

import numpy as np
import pandas as pd
import pytest

from helios.ml.baselines import (
    RESULT_COLUMNS,
    LogisticBaselineConfig,
    MLPBaselineConfig,
    majority_accuracy,
    run_baseline,
    run_logistic_baseline,
    run_mlp_baseline,
    summarise,
)
from helios.ml.fi2010 import FI2010Data, FI2010Error, FI2010Split


def toy_part(n: int, seed: int = 0) -> FI2010Data:
    """Order-book columns that actually carry a signal, so the model can learn something."""
    rng = np.random.default_rng(seed)
    labels = rng.integers(1, 4, size=(n, 5)).astype(np.int8)
    lob = rng.normal(size=(n, 40))
    lob[:, 0] += labels[:, 0] * 3.0  # first column tells you the k=10 label
    return FI2010Data(lob=lob, features=rng.normal(size=(n, 104)), labels=labels)


def fast_logreg(**overrides: object) -> LogisticBaselineConfig:
    """Few iterations: these tests check the plumbing, not convergence on random data."""
    return LogisticBaselineConfig(max_iter=20, **overrides)  # type: ignore[arg-type]


def toy_split(n: int = 300) -> FI2010Split:
    return FI2010Split(train=toy_part(n, 0), val=toy_part(n // 4, 1), test=toy_part(n // 2, 2))


def test_one_row_per_seed_with_all_columns() -> None:
    results = run_logistic_baseline(toy_split(), fast_logreg(), seeds=(0, 1, 2))
    assert list(results.columns) == list(RESULT_COLUMNS)
    assert results["seed"].tolist() == [0, 1, 2]


def test_scores_are_in_range_and_beat_guessing() -> None:
    results = run_logistic_baseline(toy_split(), fast_logreg(), seeds=(0,))
    row = results.iloc[0]
    assert 0.0 <= row["accuracy"] <= 1.0
    assert 0.0 <= row["macro_f1"] <= 1.0
    assert row["accuracy"] > row["majority_accuracy"]  # the signal is learnable


def test_seeds_give_the_same_answer() -> None:
    """This solver is deterministic: equal numbers prove no hidden randomness."""
    results = run_logistic_baseline(toy_split(), fast_logreg(), seeds=(0, 1, 2))
    assert results["accuracy"].nunique() == 1
    assert results["macro_f1"].nunique() == 1


def test_lineage_is_recorded() -> None:
    row = run_logistic_baseline(toy_split(), fast_logreg(), seeds=(0,)).iloc[0]
    assert len(row["code_commit"]) == 40  # the git commit the result came from
    assert isinstance(bool(row["dirty"]), bool)
    assert len(row["config_hash"]) == 64
    assert row["created_at"].endswith("+00:00")


def test_same_config_gives_the_same_hash() -> None:
    a = run_logistic_baseline(toy_split(), fast_logreg(), seeds=(0,))
    b = run_logistic_baseline(toy_split(), fast_logreg(), seeds=(0,))
    assert a["config_hash"].iloc[0] == b["config_hash"].iloc[0]


def test_different_config_gives_a_different_hash() -> None:
    a = run_logistic_baseline(toy_split(), fast_logreg(horizon=10), seeds=(0,))
    b = run_logistic_baseline(toy_split(), fast_logreg(horizon=50), seeds=(0,))
    assert a["config_hash"].iloc[0] != b["config_hash"].iloc[0]


def test_majority_accuracy() -> None:
    train = np.array([1, 1, 1, 2, 3])  # class 1 is commonest
    test = np.array([1, 1, 2, 3])
    assert majority_accuracy(train, test) == pytest.approx(0.5)


def test_bad_horizon_is_rejected() -> None:
    with pytest.raises(FI2010Error, match="horizon must be one of"):
        run_logistic_baseline(toy_split(), fast_logreg(horizon=7), seeds=(0,))


def test_no_seeds_is_rejected() -> None:
    with pytest.raises(FI2010Error, match="at least one seed"):
        run_logistic_baseline(toy_split(), fast_logreg(), seeds=())


# ---------------------------------------------------------------- the neural network (063)


def small_mlp() -> MLPBaselineConfig:
    """Tiny and short: these tests check the wiring, not the accuracy."""
    return MLPBaselineConfig(hidden_layer_sizes=(8,), max_iter=5, batch_size=64)


def test_the_network_runs_once_per_seed() -> None:
    results = run_mlp_baseline(toy_split(200), small_mlp(), seeds=(0, 1))
    assert list(results.columns) == list(RESULT_COLUMNS)
    assert results["seed"].tolist() == [0, 1]
    assert set(results["model"]) == {"mlp"}


def test_seeds_really_differ_for_the_network() -> None:
    """Random starting weights, so identical numbers would mean the seed is being ignored."""
    results = run_mlp_baseline(toy_split(400), small_mlp(), seeds=(0, 1, 2))
    assert results["macro_f1"].nunique() > 1


def test_the_same_seed_repeats_exactly() -> None:
    first = run_mlp_baseline(toy_split(200), small_mlp(), seeds=(0,))
    second = run_mlp_baseline(toy_split(200), small_mlp(), seeds=(0,))
    assert first["macro_f1"].iloc[0] == second["macro_f1"].iloc[0]


def test_early_stopping_stays_off() -> None:
    """It would shuffle a validation slice out of the training data, mixing up time order."""
    assert "early_stopping" not in MLPBaselineConfig().model_dump()
    model = run_mlp_baseline(toy_split(200), small_mlp(), seeds=(0,))
    assert model["model"].iloc[0] == "mlp"


def test_the_two_models_have_different_fingerprints() -> None:
    logreg = run_logistic_baseline(toy_split(200), fast_logreg(), seeds=(0,))
    mlp = run_mlp_baseline(toy_split(200), small_mlp(), seeds=(0,))
    assert logreg["config_hash"].iloc[0] != mlp["config_hash"].iloc[0]


def test_an_unknown_config_is_refused() -> None:
    from helios.ml.baselines import BaselineConfig

    with pytest.raises(FI2010Error, match="no model is defined"):
        run_baseline(toy_split(100), BaselineConfig(model="wishful_thinking"), seeds=(0,))


# ---------------------------------------------------------------- the summary table


def test_summary_has_mean_and_spread() -> None:
    results = run_mlp_baseline(toy_split(300), small_mlp(), seeds=(0, 1, 2))
    summary = summarise(results)
    assert len(summary) == 1
    row = summary.iloc[0]
    assert row["seeds"] == 3
    assert row["macro_f1_std"] >= 0
    assert min(results["macro_f1"]) <= row["macro_f1_mean"] <= max(results["macro_f1"])


def test_models_are_summarised_separately() -> None:
    both = pd.concat(
        [
            run_logistic_baseline(toy_split(200), fast_logreg(), seeds=(0, 1)),
            run_mlp_baseline(toy_split(200), small_mlp(), seeds=(0, 1)),
        ],
        ignore_index=True,
    )
    summary = summarise(both)
    assert set(summary["model"]) == {"logistic_regression", "mlp"}


def test_one_seed_reports_zero_spread() -> None:
    summary = summarise(run_logistic_baseline(toy_split(200), fast_logreg(), seeds=(0,)))
    assert summary["macro_f1_std"].iloc[0] == 0.0


def test_summarising_nothing_is_refused() -> None:
    with pytest.raises(FI2010Error, match="no results to summarise"):
        summarise(pd.DataFrame())
