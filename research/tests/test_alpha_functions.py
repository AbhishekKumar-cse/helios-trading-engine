"""Golden values, gaps, selected branches and causality for the eight DSL functions."""

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from helios.alpha.definition import load_alpha_definition
from helios.alpha.evaluator import DSLEvaluationError, evaluate_expression
from helios.features.runner import FeatureFrame

HOUR = 3_600_000_000


def frame(values: list[float], times: list[int] | None = None) -> FeatureFrame:
    n = len(values)
    index = pd.Index(np.arange(n) * 10 + 5)
    data = pd.DataFrame(
        {
            "x": values,
            "y": np.arange(n, dtype=float) + 10,
            "gate": (np.arange(n) % 2 == 0).astype(float),
        },
        index=index,
        dtype=float,
    )
    stamps = np.arange(n, dtype=np.int64) * HOUR if times is None else times
    return FeatureFrame(
        "BTCUSDT",
        pd.Series(stamps, index=index),
        data,
        pd.DataFrame(True, index=index, columns=data.columns),
    )


@pytest.mark.parametrize(
    "source,expected",
    [
        ("ts_mean(x, 3)", [np.nan, np.nan, 2, 3]),
        ("ts_std(x, 3)", [np.nan, np.nan, 1, 1]),
        ("zscore(x, 3)", [np.nan, np.nan, 1, 1]),
        ("rank_ts(x, 3)", [np.nan, np.nan, 1, 1]),
        ("lag(x, 1)", [np.nan, 1, 2, 3]),
        ("lag(x, 2)", [np.nan, np.nan, 1, 2]),
        ("sign(x - 2)", [-1, 0, 1, 1]),
        ("clip(x, 2, 3)", [2, 2, 3, 3]),
        ("where(gate, x, -x)", [1, -2, 3, -4]),
        ("lag(ts_mean(x, 2), 1)", [np.nan, np.nan, 1.5, 2.5]),
        ("ts_mean(lag(x, 1), 2)", [np.nan, np.nan, 1.5, 2.5]),
        ("clip(zscore(x, 3) * -2, -1, 1)", [np.nan, np.nan, -1, -1]),
    ],
)
def test_hand_calculated_values(source: str, expected: list[float]) -> None:
    inputs = frame([1, 2, 3, 4])
    result = evaluate_expression(source, inputs, interval="1h")
    np.testing.assert_allclose(result.values, expected, equal_nan=True)
    np.testing.assert_array_equal(result.available, np.isfinite(expected))
    pd.testing.assert_series_equal(result.open_time, inputs.open_time)


def test_sample_std_and_zscore_conventions_match_existing_helpers() -> None:
    inputs = frame([1, 2, 3, 4])
    std = evaluate_expression("ts_std(x, 4)", inputs, interval="1h")
    score = evaluate_expression("zscore(x, 4)", inputs, interval="1h")
    assert std.values.iloc[-1] == pytest.approx(math.sqrt(5 / 3))
    assert score.values.iloc[-1] == pytest.approx(1.5 / math.sqrt(5 / 3))


def test_ranks_use_average_ties_and_constant_windows_are_defined() -> None:
    ranked = evaluate_expression("rank_ts(x, 3)", frame([1, 2, 2, 4]), interval="1h")
    np.testing.assert_allclose(ranked.values, [np.nan, np.nan, 2.5 / 3, 1], equal_nan=True)
    constant = frame([5, 5, 5, 5])
    assert evaluate_expression("rank_ts(x, 3)", constant, interval="1h").values.iloc[
        -1
    ] == pytest.approx(2 / 3)
    assert evaluate_expression("ts_std(x, 3)", constant, interval="1h").values.iloc[-1] == 0
    assert not evaluate_expression("zscore(x, 3)", constant, interval="1h").available.any()


@pytest.mark.parametrize(
    "source", ["ts_mean(x, 3)", "ts_std(x, 3)", "zscore(x, 3)", "rank_ts(x, 3)"]
)
def test_rolling_masks_recover_only_after_a_full_available_window(source: str) -> None:
    inputs = frame([1, 2, 3, 4, 5, 6, 7])
    inputs.available.iloc[2, 0] = False  # even though the stored value remains finite
    result = evaluate_expression(source, inputs, interval="1h")
    assert result.available.tolist() == [False, False, False, False, False, True, True]
    assert result.values.iloc[:5].isna().all()


@pytest.mark.parametrize(
    "source", ["ts_mean(x, 3)", "ts_std(x, 3)", "zscore(x, 3)", "rank_ts(x, 3)"]
)
@pytest.mark.parametrize("interval,step", [("1h", HOUR), ("1m", 60_000_000)])
def test_gaps_restart_rolling_availability(source: str, interval: str, step: int) -> None:
    inputs = frame([1, 2, 3, 4, 5, 6], times=[i * step for i in [0, 1, 2, 4, 5, 6]])
    result = evaluate_expression(source, inputs, interval=interval)
    assert result.available.tolist() == [False, False, True, False, False, True]


def test_lag_requires_contiguous_elapsed_time_but_not_current_input_availability() -> None:
    inputs = frame([1, 2, 3, 4, 5], times=[0, HOUR, 3 * HOUR, 4 * HOUR, 5 * HOUR])
    inputs.available.iloc[3, 0] = False
    lagged = evaluate_expression("lag(x, 1)", inputs, interval="1h")
    np.testing.assert_allclose(lagged.values, [np.nan, 1, np.nan, 3, np.nan], equal_nan=True)
    assert lagged.available.tolist() == [False, True, False, True, False]


def test_lag_reads_only_the_endpoint_mask_not_intermediate_feature_masks() -> None:
    inputs = frame([1, 2, 3, 4])
    inputs.available.iloc[1, 0] = False
    result = evaluate_expression("lag(x, 2)", inputs, interval="1h")
    assert result.available.tolist() == [False, False, True, False]
    assert result.values.iloc[2] == 1


@pytest.mark.parametrize("source", ["ts_mean(1, 1)", "rank_ts(1, 1)", "lag(1, 1)"])
def test_off_grid_rows_do_not_create_temporal_values(source: str) -> None:
    inputs = frame([1, 2, 3], times=[1, HOUR + 1, 2 * HOUR + 1])
    result = evaluate_expression(source, inputs, interval="1h")
    assert not result.available.any()


def test_sign_and_clip_keep_nonfinite_inputs_unavailable() -> None:
    inputs = frame([-2, 0, 2, np.inf, np.nan])
    signed = evaluate_expression("sign(x)", inputs)
    clipped = evaluate_expression("clip(x, -1, 1)", inputs)
    np.testing.assert_allclose(signed.values, [-1, 0, 1, np.nan, np.nan], equal_nan=True)
    np.testing.assert_allclose(clipped.values, [-1, 0, 1, np.nan, np.nan], equal_nan=True)
    assert (
        signed.available.tolist() == clipped.available.tolist() == [True, True, True, False, False]
    )


def test_where_uses_condition_and_selected_branch_masks_only() -> None:
    inputs = frame([1, 2, 3, 4])
    inputs.available["x"] = [True, False, False, True]
    inputs.available["y"] = [False, True, True, False]
    result = evaluate_expression("where(gate, x, y)", inputs)
    np.testing.assert_allclose(result.values, [1, 11, np.nan, np.nan], equal_nan=True)
    assert result.available.tolist() == [True, True, False, False]
    inputs.available.iloc[0, 2] = False
    assert not evaluate_expression("where(gate, x, y)", inputs).available.iloc[0]


def test_where_does_not_promote_unknown_conditions_or_unused_invalid_branch_values() -> None:
    inputs = frame([1, 0, -1, np.nan])
    result = evaluate_expression("where(x, 1, 1 / 0)", inputs)
    np.testing.assert_allclose(result.values, [1, np.nan, 1, np.nan], equal_nan=True)
    with pytest.raises(DSLEvaluationError, match="unknown feature"):
        evaluate_expression("where(1, x, unknown_feature)", inputs)


def test_controls_bind_finite_scalar_parameters_and_constant_arithmetic() -> None:
    result = evaluate_expression(
        "clip(ts_mean(x, w + 1), -bound, bound)",
        frame([1, 2, 3, 4]),
        params={"w": 2, "bound": 2.5},
        interval="1h",
    )
    np.testing.assert_allclose(result.values, [np.nan, np.nan, 2, 2.5], equal_nan=True)


@pytest.mark.parametrize(
    "source",
    [
        "lag(x, -1)",
        "lag(x, 0)",
        "lag(x, 1.5)",
        "ts_mean(x, 0)",
        "ts_std(x, 1)",
        "zscore(x, 1)",
        "rank_ts(x, -1)",
        "ts_mean(x, y)",
        "ts_mean(x, 1 / 0)",
        "ts_mean(x, 1e308 * 10)",
        "clip(x, 1, -1)",
        "clip(x, y, 4)",
    ],
)
def test_invalid_function_controls_fail_before_any_result(source: str) -> None:
    with pytest.raises(DSLEvaluationError):
        evaluate_expression(source, frame([1, 2, 3, 4]), interval="1h")


@pytest.mark.parametrize("source", ["ts_mean(x, 1000000000)", "lag(x, 1000000000)"])
def test_history_shorter_than_control_is_entirely_unavailable(source: str) -> None:
    result = evaluate_expression(source, frame([1, 2, 3]), interval="1h")
    assert result.values.isna().all() and not result.available.any()


def test_invalid_interval_has_a_clear_evaluation_error() -> None:
    with pytest.raises(DSLEvaluationError, match="unknown interval"):
        evaluate_expression("ts_mean(x, 2)", frame([1, 2, 3]), interval="unknown")


def test_step_085_quant_examples_now_evaluate() -> None:
    examples = Path(__file__).resolve().parents[2] / "configs/alphas/examples"
    inputs = frame([1, 2, 3])
    inputs.values.columns = ["log_return_24", "close_over_mean_12", "gate"]
    inputs.available.columns = inputs.values.columns
    for path in examples.glob("*.yaml"):
        definition = load_alpha_definition(path)
        if definition.expression is not None:
            result = evaluate_expression(definition.expression, inputs, params=definition.params)
            assert result.available.all()


@pytest.mark.parametrize(
    "source",
    [
        "zscore(x, 3)",
        "ts_mean(x, 3)",
        "ts_std(x, 3)",
        "rank_ts(x, 3)",
        "lag(x, 2)",
        "sign(x)",
        "clip(x, -1, 1)",
        "where(gate, x, y)",
    ],
)
@settings(max_examples=20, deadline=None)
@given(
    st.lists(st.floats(min_value=-10, max_value=10, allow_nan=False), min_size=12, max_size=25),
    st.integers(min_value=5, max_value=10),
)
def test_every_function_preserves_earlier_values_when_future_changes(
    source: str, data: list[float], cut: int
) -> None:
    inputs = frame(data)
    before = evaluate_expression(source, inputs, interval="1h")
    changed = frame(data)
    changed.values.iloc[cut:] = 999
    changed.available.iloc[cut:] = False
    after = evaluate_expression(source, changed, interval="1h")
    truncated = FeatureFrame(
        inputs.symbol,
        inputs.open_time.iloc[:cut],
        inputs.values.iloc[:cut],
        inputs.available.iloc[:cut],
    )
    shorter = evaluate_expression(source, truncated, interval="1h")
    np.testing.assert_array_equal(before.values.iloc[:cut], after.values.iloc[:cut])
    np.testing.assert_array_equal(before.values.iloc[:cut], shorter.values)
    np.testing.assert_array_equal(before.available.iloc[:cut], after.available.iloc[:cut])
    np.testing.assert_array_equal(before.available.iloc[:cut], shorter.available)
