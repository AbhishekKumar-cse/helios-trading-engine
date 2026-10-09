"""Hand-calculated arithmetic, availability, chronology and DSL boundary tests (088)."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from helios.alpha.definition import AlphaDefinition
from helios.alpha.evaluator import DSLEvaluationError, evaluate_expression
from helios.alpha.parser import DSLParseError
from helios.features import basic  # noqa: F401 -- populate the production registry
from helios.features.runner import FeatureFrame, compute_features


def frame() -> FeatureFrame:
    index = pd.Index([11, 22, 33, 44], name="source_row")
    return FeatureFrame(
        symbol="BTCUSDT",
        open_time=pd.Series([0, 3_600_000_000, 7_200_000_000, 14_400_000_000], index=index),
        values=pd.DataFrame({"x": [2.0, 4.0, -6.0, 0.0], "y": [1.0, 2.0, 3.0, -2.0]}, index=index),
        available=pd.DataFrame({"x": [True] * 4, "y": [True] * 4}, index=index),
    )


@pytest.mark.parametrize(
    "source,expected",
    [
        ("x + y", [3, 6, -3, -2]),
        ("x - y", [1, 2, -9, 2]),
        ("x * y", [2, 8, -18, 0]),
        ("x / y", [2, 2, -2, 0]),
        ("x + y * 2", [4, 8, 0, -4]),
        ("(x + y) * 2", [6, 12, -6, -4]),
        ("x - y - 1", [0, 1, -10, 1]),
        ("x / y / 2", [1, 1, -1, 0]),
        ("-x + +y", [-1, -2, 9, -2]),
        ("--x", [2, 4, -6, 0]),
        ("0.25", [0.25] * 4),
        ("x", [2, 4, -6, 0]),
        ("-1e-3", [-0.001] * 4),
    ],
)
def test_arithmetic_matches_hand_calculations(source: str, expected: list[float]) -> None:
    inputs = frame()
    result = evaluate_expression(source, inputs)
    np.testing.assert_allclose(result.values, expected)
    assert result.available.all()
    assert result.values.dtype == np.float64
    assert result.available.dtype == bool
    assert result.symbol == "BTCUSDT"
    pd.testing.assert_series_equal(result.open_time, inputs.open_time)
    assert result.values.index.equals(inputs.values.index)
    assert result.rows == 4  # includes a time gap without generating or reordering rows


@pytest.mark.parametrize("source", ["x + y", "x - y", "x * y", "x / y"])
def test_binary_masks_require_both_operands(source: str) -> None:
    inputs = frame()
    inputs.available["x"] = [True, False, True, True]
    inputs.available["y"] = [True, True, False, True]
    result = evaluate_expression(source, inputs)
    assert result.available.tolist() == [True, False, False, True]
    assert result.values.iloc[1:3].isna().all()


@pytest.mark.parametrize("source", ["x", "-x", "0 * x", "x - x", "x + 1"])
def test_masked_finite_inputs_cannot_become_available(source: str) -> None:
    inputs = frame()
    inputs.available.loc[22, "x"] = False
    result = evaluate_expression(source, inputs)
    assert not result.available.loc[22]
    assert pd.isna(result.values.loc[22])


def test_unused_unavailable_columns_do_not_mask_results() -> None:
    inputs = frame()
    inputs.available["y"] = False
    assert evaluate_expression("x * 2", inputs).available.all()
    assert evaluate_expression("0", inputs).available.all()


def test_zero_is_valid_but_zero_divisors_are_unavailable() -> None:
    inputs = frame()
    inputs.values["y"] = [0.0, -0.0, 2.0, 2.0]
    result = evaluate_expression("x / y", inputs)
    assert result.available.tolist() == [False, False, True, True]
    np.testing.assert_allclose(result.values, [np.nan, np.nan, -3, 0], equal_nan=True)


def test_nonfinite_input_and_overflow_are_unavailable_without_warnings() -> None:
    inputs = frame()
    inputs.values["x"] = [np.nan, np.inf, -np.inf, 1e308]
    with np.errstate(all="raise"):
        result = evaluate_expression("x * 10", inputs)
    assert not result.available.any()
    assert result.values.isna().all()


def test_output_is_raw_and_not_yet_clipped() -> None:
    assert evaluate_expression("x * 10", frame()).values.tolist() == [20, 40, -60, 0]


def test_feature_runner_warmup_and_gap_masks_flow_into_alpha() -> None:
    # Synthetic bars test the actual production feature/evaluator boundary.
    hours = np.delete(np.arange(40, dtype=np.int64), 15)
    close = np.arange(len(hours), dtype=float) + 100
    bars = pd.DataFrame(
        {
            "open_time": hours * 3_600_000_000,
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": np.ones(len(hours)),
        }
    )
    features = compute_features(
        bars, "1h", names=["log_return_1", "close_over_mean_12"], symbol="BTCUSDT"
    )
    result = evaluate_expression("log_return_1 - 2 * close_over_mean_12", features)
    expected_mask = features.available.all(axis=1)
    pd.testing.assert_series_equal(result.available, expected_mask.rename("available"))
    expected = features.values["log_return_1"] - 2 * features.values["close_over_mean_12"]
    pd.testing.assert_series_equal(result.values, expected.where(expected_mask).rename("alpha"))
    assert not result.available.iloc[:11].any()
    assert not result.available.iloc[15:26].any()
    assert result.available.iloc[-1]


def test_nullable_numeric_values_are_masked_and_constant_zero_division_is_unavailable() -> None:
    inputs = frame()
    inputs.values["x"] = pd.Series([1, pd.NA, 0, 2], index=inputs.values.index, dtype="Float64")
    result = evaluate_expression("x", inputs)
    assert result.available.tolist() == [True, False, True, True]
    assert not evaluate_expression("1 / 0", inputs).available.any()
    assert evaluate_expression("1 / 0", inputs).values.isna().all()


def test_numeric_parameters_and_loaded_definition_metadata() -> None:
    idea = AlphaDefinition(
        alpha_id="t_arithmetic",
        version=1,
        name="Arithmetic test",
        provenance="QUANT",
        feature_set_version="v1",
        horizon_family="H-HOURLY",
        horizon_periods=1,
        params={"scale": 0.5, "offset": 2},
        expression="x * scale + offset",
        author="test_author",
        code_commit="a" * 40,
    )
    assert idea.expression is not None
    result = evaluate_expression(idea.expression, frame(), params=idea.params)
    assert result.values.tolist() == [3, 4, -1, 2]


@pytest.mark.parametrize(
    "params",
    [
        {"scale": True},
        {"scale": "1"},
        {"scale": [1]},
        {"scale": None},
        {"scale": float("nan")},
        {"scale": float("inf")},
        {"scale": 10**400},
        {"x": 1},
        {"sign": 1},
        {"_private": 1},
        {"x__private": 1},
    ],
)
def test_invalid_or_ambiguous_parameters_are_rejected(params: dict[str, object]) -> None:
    with pytest.raises(DSLEvaluationError):
        evaluate_expression("x", frame(), params=params)


@pytest.mark.parametrize("source", ["unknown_feature + 1", "ret_1", "scale * x"])
def test_unknown_names_fail_instead_of_aliasing_or_zero_filling(source: str) -> None:
    with pytest.raises(DSLEvaluationError, match="unknown feature or parameter"):
        evaluate_expression(source, frame())


@pytest.mark.parametrize("source", ["sign(x)", "lag(x, 1)", "zscore(x, 24)"])
def test_functions_wait_for_step_089(source: str) -> None:
    with pytest.raises(DSLEvaluationError, match="function calls"):
        evaluate_expression(source, frame())


def test_unsafe_source_is_rejected_before_execution(tmp_path: Path) -> None:
    marker = tmp_path / "not_executed"
    with pytest.raises(DSLParseError):
        evaluate_expression(f"__import__('pathlib').Path({str(marker)!r}).touch()", frame())
    assert not marker.exists()


def test_input_and_output_do_not_share_mutable_data() -> None:
    inputs = frame()
    values = inputs.values.copy(deep=True)
    masks = inputs.available.copy(deep=True)
    timestamps = inputs.open_time.copy(deep=True)
    result = evaluate_expression("x", inputs)
    result.values.iloc[0] = 999
    result.available.iloc[0] = False
    result.open_time.iloc[0] = 999
    pd.testing.assert_frame_equal(inputs.values, values)
    pd.testing.assert_frame_equal(inputs.available, masks)
    pd.testing.assert_series_equal(inputs.open_time, timestamps)


@pytest.mark.parametrize(
    "problem",
    [
        "mask_index",
        "time_index",
        "columns",
        "duplicate_columns",
        "duplicate_index",
        "duplicate_time",
        "unsorted_time",
        "float_time",
    ],
)
def test_misaligned_or_ambiguous_frames_fail(problem: str) -> None:
    inputs = frame()
    if problem == "mask_index":
        inputs.available.index = pd.RangeIndex(4)
    elif problem == "time_index":
        inputs.open_time.index = pd.RangeIndex(4)
    elif problem == "columns":
        inputs.available.columns = ["x", "other"]
    elif problem == "duplicate_columns":
        inputs.values.columns = ["x", "x"]
        inputs.available.columns = ["x", "x"]
    elif problem == "duplicate_index":
        inputs.values.index = pd.Index([11, 22, 22, 44])
    elif problem == "duplicate_time":
        inputs.open_time.iloc[1] = 0
    elif problem == "unsorted_time":
        inputs.open_time.iloc[0] = 20_000_000_000
    elif problem == "float_time":
        inputs = FeatureFrame(
            inputs.symbol, inputs.open_time.astype(float), inputs.values, inputs.available
        )
    with pytest.raises(DSLEvaluationError):
        evaluate_expression("x", inputs)


@pytest.mark.parametrize("kind", ["string", "complex", "bool", "integer_mask", "nullable_mask"])
def test_unsafe_feature_or_mask_types_fail(kind: str) -> None:
    inputs = frame()
    if kind == "string":
        inputs.values["x"] = "2"
    elif kind == "complex":
        inputs.values["x"] = 1j
    elif kind == "bool":
        inputs.values["x"] = True
    elif kind == "integer_mask":
        inputs.available["x"] = 1
    else:
        inputs.available["x"] = pd.Series(
            [True, pd.NA, True, True], index=inputs.values.index, dtype="boolean"
        )
    with pytest.raises(DSLEvaluationError):
        evaluate_expression("x", inputs)


def test_empty_frame_fails_explicitly() -> None:
    inputs = frame()
    empty = FeatureFrame(
        inputs.symbol, inputs.open_time.iloc[:0], inputs.values.iloc[:0], inputs.available.iloc[:0]
    )
    with pytest.raises(DSLEvaluationError, match="no feature rows"):
        evaluate_expression("1", empty)


@settings(max_examples=30, deadline=None)
@given(
    st.lists(st.floats(min_value=-100, max_value=100, allow_nan=False), min_size=5, max_size=40),
    st.integers(min_value=1, max_value=4),
)
def test_future_perturbation_and_truncation_preserve_earlier_outputs(
    data: list[float], cut: int
) -> None:
    values = pd.DataFrame({"x": data, "y": np.arange(len(data), dtype=float) + 1})
    masks = pd.DataFrame(True, index=values.index, columns=values.columns)
    times = pd.Series(np.arange(len(data), dtype=np.int64) * 3_600_000_000)
    original = FeatureFrame("BTCUSDT", times, values, masks)
    source = "(x + y) / (y + 1) - 2 * x"
    baseline = evaluate_expression(source, original)
    changed_values, changed_masks = values.copy(), masks.copy()
    changed_values.iloc[cut:] = 999
    changed_masks.iloc[cut:] = False
    changed = evaluate_expression(
        source, FeatureFrame("BTCUSDT", times, changed_values, changed_masks)
    )
    truncated = evaluate_expression(
        source, FeatureFrame("BTCUSDT", times.iloc[:cut], values.iloc[:cut], masks.iloc[:cut])
    )
    np.testing.assert_array_equal(baseline.values.iloc[:cut], changed.values.iloc[:cut])
    np.testing.assert_array_equal(baseline.values.iloc[:cut], truncated.values)
    np.testing.assert_array_equal(baseline.available.iloc[:cut], changed.available.iloc[:cut])
    np.testing.assert_array_equal(baseline.available.iloc[:cut], truncated.available)
