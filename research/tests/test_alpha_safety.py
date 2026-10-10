"""Forbidden-expression suite and preflight integration for ALG-003 (step 090)."""

import ast
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from helios.alpha.errors import DSLEvaluationError
from helios.alpha.evaluator import evaluate_expression
from helios.alpha.parser import DSLParseError
from helios.alpha.safety import validate_expression
from helios.features.runner import FeatureFrame


def frame() -> FeatureFrame:
    return FeatureFrame(
        "BTCUSDT",
        pd.Series(np.arange(4, dtype=np.int64) * 3_600_000_000),
        pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0]}),
        pd.DataFrame({"x": [True] * 4}),
    )


@pytest.mark.parametrize(
    "source",
    [
        "lag(x, -1)",
        "lag(x, 0)",
        "lag(x, -0.0)",
        "lag(x, 2 - 3)",
        "lag(x, k)",
        "lag(x, 0.5)",
        "ts_mean(x, 0)",
        "ts_mean(x, -1)",
        "ts_std(x, 1)",
        "zscore(x, 1)",
        "rank_ts(x, 0)",
        "ts_mean(x, 2.5)",
        "lag(x, 9223372036854775808)",
        "ts_mean(x, 9223372036854775808)",
        "ts_mean(x, x)",
        "lag(x, sign(x))",
        "clip(x, x, 1)",
        "clip(x, -1, ts_mean(x, 2))",
        "clip(x, 2, 1)",
        "ts_mean(x, 1 / 0)",
        "lag(x, 1e308 * 1e308)",
        "clip(x, -1, 1e308 * 1e308)",
        "missing",
        "0 * missing",
        "ts_mean(missing, 1000000)",
        "where(1, x, missing)",
        "where(0, missing, x)",
        "where(1, x, lag(x, -1))",
        "where(0, clip(x, 3, 2), x)",
    ],
)
def test_semantic_errors_raise_before_any_series_evaluation(source: str) -> None:
    # A valid left subexpression must not be computed before a forbidden right one.
    source = f"ts_mean(x, 2) + ({source})"
    with patch("helios.alpha.evaluator._Evaluator.visit") as visit:
        with pytest.raises(DSLEvaluationError):
            evaluate_expression(source, frame(), params={"k": 0}, interval="1h")
        visit.assert_not_called()
    with pytest.raises(DSLEvaluationError):
        validate_expression(source, feature_names=("x",), params={"k": 0}, interval="1h")


@pytest.mark.parametrize(
    "source",
    [
        "mean(x)",
        "std(x)",
        "sum(x)",
        "min(x)",
        "max(x)",
        "rank(x)",
        "quantile(x, 0.95)",
        "full_sample_zscore(x)",
        "normalize(x)",
        "pca(x)",
        "x.mean()",
        "np.mean(x)",
        "x[-1]",
        "zscore(x)",
        "ts_mean(x)",
        "where(1, x, mean(x))",
        "where(0, evil(x), x)",
        "lag(x, periods=-1)",
        "lag(x, True)",
        "lag(x, 1e309)",
    ],
)
def test_full_sample_and_unknown_functions_remain_structurally_impossible(source: str) -> None:
    with pytest.raises(DSLParseError):
        validate_expression(source, feature_names=("x",), interval="1h")
    with patch("helios.alpha.evaluator._Evaluator.visit") as visit:
        with pytest.raises(DSLParseError):
            evaluate_expression(source, frame(), interval="1h")
        visit.assert_not_called()


@pytest.mark.parametrize("source", ["lag(x, 1)", "ts_mean(x, 2)", "where(1, x, lag(x, 1))"])
def test_missing_time_contract_is_rejected_even_in_unselected_branch(source: str) -> None:
    with pytest.raises(DSLEvaluationError, match="interval is required"):
        validate_expression(source, feature_names=("x",))


@pytest.mark.parametrize("params", [{"k": True}, {"k": float("inf")}, {"k": "2"}, {"x": 2}])
def test_preflight_checks_parameter_schema(params: dict[str, object]) -> None:
    with pytest.raises(DSLEvaluationError):
        validate_expression("x", feature_names=("x",), params=params)


@pytest.mark.parametrize("interval", ["", "1w", "nonsense"])
def test_bad_explicit_interval_raises(interval: str) -> None:
    with pytest.raises(DSLEvaluationError):
        validate_expression("x", feature_names=("x",), interval=interval)


def test_preflight_accepts_causal_composition_and_reuses_control_rules() -> None:
    source = "where(sign(x), clip(zscore(lag(x, k), w), -b, b), rank_ts(x, w))"
    params = {"k": 1, "w": 2, "b": 0.75}
    tree = validate_expression(source, feature_names=("x",), params=params, interval="1h")
    assert isinstance(tree, ast.Expression)
    result = evaluate_expression(source, frame(), params=params, interval="1h")
    np.testing.assert_allclose(result.values, [np.nan, np.nan, 2**-0.5, 2**-0.5], equal_nan=True)


def test_valid_large_trailing_window_is_not_a_full_sample_reducer() -> None:
    # A window exceeding available history remains unavailable, not implicitly shortened.
    validate_expression("ts_mean(x, 1000000)", feature_names=("x",), interval="1h")
    result = evaluate_expression("ts_mean(x, 1000000)", frame(), interval="1h")
    assert result.values.isna().all()
    assert not result.available.any()


def test_reducer_spelling_is_not_an_executable_alias_when_used_as_a_feature() -> None:
    validate_expression("mean + scale", feature_names=("mean",), params={"scale": 2})
    with pytest.raises(DSLParseError, match="unknown DSL function"):
        validate_expression("mean(mean)", feature_names=("mean",))


@given(st.integers(max_value=0, min_value=-(2**62)))
@settings(max_examples=30, deadline=None)
def test_nonpositive_parameter_lags_always_fail(k: int) -> None:
    with pytest.raises(DSLEvaluationError):
        validate_expression("lag(x, k)", feature_names=("x",), params={"k": k}, interval="1h")


@given(st.integers(min_value=1, max_value=100))
@settings(max_examples=20, deadline=None)
def test_scalar_arithmetic_cannot_disguise_a_nonpositive_lag(k: int) -> None:
    with pytest.raises(DSLEvaluationError):
        validate_expression(
            "where(1, x, lag(x, 1 - k))",
            feature_names=("x",),
            params={"k": k},
            interval="1h",
        )
