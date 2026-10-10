"""Five-coin golden values, historical membership, alignment and causality (091)."""

from datetime import date
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from helios.alpha.cross_sectional import evaluate_universe_expression
from helios.alpha.errors import DSLEvaluationError
from helios.alpha.evaluator import evaluate_expression
from helios.alpha.parser import DSLParseError
from helios.alpha.safety import validate_expression
from helios.features.runner import FeatureFrame

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
HOUR = 3_600_000_000
DATES = dict.fromkeys(SYMBOLS, date(1970, 1, 1))


def frames() -> dict[str, FeatureFrame]:
    result = {}
    for i, symbol in enumerate(SYMBOLS):
        index = pd.Index([10 + i, 20 + i, 30 + i], name="source_row")
        result[symbol] = FeatureFrame(
            symbol,
            pd.Series([0, HOUR, 2 * HOUR], index=index, dtype="int64"),
            pd.DataFrame({"x": [float(i + 1), float(5 - i), 7.0]}, index=index),
            pd.DataFrame({"x": [True] * 3}, index=index),
        )
    return result


@pytest.mark.parametrize("function", ["cs_rank", "cs_demean"])
def test_five_coin_golden_values_and_metadata(function: str) -> None:
    inputs = frames()
    result = evaluate_universe_expression(f"{function}(x)", inputs, listing_dates=DATES)
    for i, symbol in enumerate(SYMBOLS):
        expected = [(i + 1) / 5, (5 - i) / 5, 3 / 5] if function == "cs_rank" else [i - 2, 2 - i, 0]
        np.testing.assert_allclose(result[symbol].values, expected, atol=1e-14)
        assert result[symbol].available.all()
        assert result[symbol].symbol == symbol
        pd.testing.assert_series_equal(result[symbol].open_time, inputs[symbol].open_time)
        assert result[symbol].values.index.equals(inputs[symbol].values.index)
        assert result[symbol].values.dtype == np.float64
        assert result[symbol].available.dtype == bool


def test_partial_ties_use_average_ranks() -> None:
    inputs = frames()
    for symbol, value in zip(SYMBOLS, [1, 1, 3, 3, 5], strict=True):
        inputs[symbol].values["x"] = value
    ranked = evaluate_universe_expression("cs_rank(x)", inputs, listing_dates=DATES)
    assert [ranked[s].values.iloc[0] for s in SYMBOLS] == [0.3, 0.3, 0.7, 0.7, 1.0]


@pytest.mark.parametrize("function", ["cs_rank", "cs_demean"])
@pytest.mark.parametrize("defect", ["mask", "nan", "inf", "missing_row", "off_time"])
def test_missing_listed_peer_invalidates_only_that_exact_cross_section(
    function: str, defect: str
) -> None:
    inputs = frames()
    bad = inputs["SOLUSDT"]
    if defect == "mask":
        bad.available.iloc[1, 0] = False
    elif defect in {"nan", "inf"}:
        bad.values.iloc[1, 0] = float(defect)
    elif defect == "missing_row":
        inputs["SOLUSDT"] = FeatureFrame(
            bad.symbol,
            bad.open_time.iloc[[0, 2]],
            bad.values.iloc[[0, 2]],
            bad.available.iloc[[0, 2]],
        )
    else:
        bad.open_time.iloc[1] += 1
    result = evaluate_universe_expression(f"{function}(x)", inputs, listing_dates=DATES)
    for symbol in SYMBOLS:
        output = result[symbol]
        at_hour = output.open_time == HOUR
        assert not output.available.loc[at_hour].any()
        assert output.values.loc[at_hour].isna().all()
        assert output.available.iloc[0]
        assert output.available.iloc[-1]
    if defect == "off_time":
        assert not result["SOLUSDT"].available.iloc[1]


@pytest.mark.parametrize("function", ["cs_rank", "cs_demean"])
def test_listing_date_is_inclusive_utc_and_unlisted_values_do_not_affect_peers(
    function: str,
) -> None:
    inputs = frames()
    dates = dict(DATES, SOLUSDT=date(1970, 1, 2))
    for f in inputs.values():
        f.open_time.iloc[:] = [23 * HOUR, 24 * HOUR, 25 * HOUR]
    inputs["SOLUSDT"].values.iloc[0, 0] = 1e100
    result = evaluate_universe_expression(f"{function}(x)", inputs, listing_dates=dates)
    assert not result["SOLUSDT"].available.iloc[0]
    assert result["SOLUSDT"].available.iloc[1]
    assert result["BTCUSDT"].values.iloc[0] == pytest.approx(0.25 if function == "cs_rank" else -2)
    assert result["BTCUSDT"].values.iloc[1] == pytest.approx(1 if function == "cs_rank" else 2)


def test_single_listed_coin_and_no_listed_coins_are_defined() -> None:
    inputs = frames()
    dates = dict.fromkeys(SYMBOLS, date(1970, 1, 2))
    none = evaluate_universe_expression("cs_rank(x)", inputs, listing_dates=dates)
    assert all(not x.available.any() for x in none.values())
    dates["BTCUSDT"] = date(1970, 1, 1)
    rank = evaluate_universe_expression("cs_rank(x)", inputs, listing_dates=dates)
    demean = evaluate_universe_expression("cs_demean(x)", inputs, listing_dates=dates)
    assert rank["BTCUSDT"].values.tolist() == [1, 1, 1]
    assert demean["BTCUSDT"].values.tolist() == [0, 0, 0]


def test_empty_future_member_is_not_silently_dropped_after_listing() -> None:
    inputs = frames()
    sol = inputs["SOLUSDT"]
    inputs["SOLUSDT"] = FeatureFrame(
        sol.symbol, sol.open_time.iloc[:0], sol.values.iloc[:0], sol.available.iloc[:0]
    )
    dates = dict(DATES, SOLUSDT=date(1970, 1, 2))
    before = evaluate_universe_expression("cs_rank(x)", inputs, listing_dates=dates)
    assert before["BTCUSDT"].available.all()
    assert before["SOLUSDT"].rows == 0
    after = evaluate_universe_expression("cs_rank(x)", inputs, listing_dates=DATES)
    assert not after["BTCUSDT"].available.any()


@pytest.mark.parametrize(
    "source", ["cs_rank(lag(x, 1))", "lag(cs_rank(x), 1)", "cs_rank(cs_demean(x))"]
)
def test_nested_time_and_cross_operations_keep_their_axes(source: str) -> None:
    result = evaluate_universe_expression(source, frames(), listing_dates=DATES, interval="1h")
    expected = [np.nan, 0.2, 1.0] if "lag" in source else [0.2, 1.0, 0.6]
    np.testing.assert_allclose(result["BTCUSDT"].values, expected, equal_nan=True)


def test_where_unselected_unavailable_cross_values_do_not_poison_constants() -> None:
    inputs = frames()
    inputs["SOLUSDT"].available.iloc[1, 0] = False
    result = evaluate_universe_expression("where(0, cs_rank(x), 2)", inputs, listing_dates=DATES)
    assert all(r.values.tolist() == [2, 2, 2] for r in result.values())


def test_constants_are_masked_before_listing_and_large_finite_mean_does_not_overflow() -> None:
    inputs = frames()
    for f in inputs.values():
        f.values["x"] = 1e308
    result = evaluate_universe_expression("cs_demean(x)", inputs, listing_dates=DATES)
    assert all(r.available.all() for r in result.values())
    assert all(np.allclose(r.values, 0) for r in result.values())
    dates = dict(DATES, SOLUSDT=date(1970, 1, 2))
    constant = evaluate_universe_expression("1", inputs, listing_dates=dates)
    assert not constant["SOLUSDT"].available.any()


@pytest.mark.parametrize("source", ["cs_rank(x)", "cs_demean(x)", "where(0, cs_rank(x), 1)"])
def test_single_coin_api_cannot_silently_rank_itself(source: str) -> None:
    with pytest.raises(DSLEvaluationError, match="universe context"):
        evaluate_expression(source, frames()["BTCUSDT"])
    with pytest.raises(DSLEvaluationError, match="universe context"):
        validate_expression(source, feature_names=("x",))
    validate_expression(source, feature_names=("x",), cross_sectional=True)


@pytest.mark.parametrize("source", ["cs_rank(x, 2)", "cs_demean()", "cs_rank(x.mean())"])
def test_cross_syntax_stays_inside_whitelist(source: str) -> None:
    with pytest.raises(DSLParseError):
        evaluate_universe_expression(source, frames(), listing_dates=DATES)


@pytest.mark.parametrize("defect", ["empty", "missing_date", "wrong_date", "wrong_symbol", "name"])
def test_bad_universe_context_rejected_before_evaluation(defect: str) -> None:
    inputs = frames()
    dates: dict[str, object] = dict(DATES)
    if defect == "empty":
        inputs = {}
    elif defect == "missing_date":
        del dates["SOLUSDT"]
    elif defect == "wrong_date":
        dates["SOLUSDT"] = "2020-08-11"
    elif defect == "wrong_symbol":
        sol = inputs["SOLUSDT"]
        inputs["SOLUSDT"] = FeatureFrame("OTHER", sol.open_time, sol.values, sol.available)
    else:
        sol = inputs["SOLUSDT"]
        inputs["SOLUSDT"] = FeatureFrame(
            sol.symbol,
            sol.open_time,
            sol.values.rename(columns={"x": "other"}),
            sol.available.rename(columns={"x": "other"}),
        )
    with patch("helios.alpha.cross_sectional._CoinEvaluator.visit") as visit:
        with pytest.raises(DSLEvaluationError):
            evaluate_universe_expression("cs_rank(x)", inputs, listing_dates=dates)  # type: ignore[arg-type]
        visit.assert_not_called()


def test_symbol_order_and_input_isolation() -> None:
    inputs = frames()
    before = inputs["BTCUSDT"].values.copy(deep=True)
    result = evaluate_universe_expression("cs_demean(x)", inputs, listing_dates=DATES)
    reordered = evaluate_universe_expression(
        "cs_demean(x)", dict(reversed(list(inputs.items()))), listing_dates=DATES
    )
    for symbol in SYMBOLS:
        pd.testing.assert_series_equal(result[symbol].values, reordered[symbol].values)
    result["BTCUSDT"].values.iloc[0] = 999
    pd.testing.assert_frame_equal(inputs["BTCUSDT"].values, before)


def test_pointwise_universe_evaluation_matches_existing_coin_api() -> None:
    inputs = frames()
    source = "clip(x * scale, -2, 2)"
    result = evaluate_universe_expression(
        source, inputs, listing_dates=DATES, params={"scale": 0.5}
    )
    for symbol in SYMBOLS:
        single = evaluate_expression(source, inputs[symbol], params={"scale": 0.5})
        pd.testing.assert_series_equal(result[symbol].values, single.values)
        pd.testing.assert_series_equal(result[symbol].available, single.available)


@pytest.mark.parametrize("source", ["ts_mean(x, cs_rank(x))", "where(0, lag(cs_rank(x), 0), x)"])
def test_cross_context_keeps_semantic_control_checks(source: str) -> None:
    with pytest.raises(DSLEvaluationError):
        evaluate_universe_expression(source, frames(), listing_dates=DATES, interval="1h")


def test_out_of_range_timestamps_are_rejected_instead_of_wrapping() -> None:
    inputs = frames()
    sol = inputs["SOLUSDT"]
    inputs["SOLUSDT"] = FeatureFrame(
        sol.symbol,
        pd.Series([2**63, 2**63 + HOUR, 2**63 + 2 * HOUR], index=sol.values.index, dtype="uint64"),
        sol.values,
        sol.available,
    )
    with pytest.raises(DSLEvaluationError, match="signed int64"):
        evaluate_universe_expression("cs_rank(x)", inputs, listing_dates=DATES)


def test_all_empty_members_return_empty_outputs_without_fabricated_timestamps() -> None:
    inputs = {
        s: FeatureFrame(f.symbol, f.open_time.iloc[:0], f.values.iloc[:0], f.available.iloc[:0])
        for s, f in frames().items()
    }
    result = evaluate_universe_expression("cs_demean(x)", inputs, listing_dates=DATES)
    assert all(r.rows == 0 for r in result.values())


@pytest.mark.parametrize("source", ["cs_rank(x)", "cs_demean(x)", "lag(cs_rank(x), 1)"])
@given(st.lists(st.floats(min_value=-100, max_value=100, allow_nan=False), min_size=5, max_size=5))
@settings(max_examples=20, deadline=None)
def test_future_peer_changes_and_truncation_cannot_change_past(
    source: str, future: list[float]
) -> None:
    inputs = frames()
    expected = evaluate_universe_expression(source, inputs, listing_dates=DATES, interval="1h")
    for symbol, value in zip(SYMBOLS, future, strict=True):
        inputs[symbol].values.iloc[2, 0] = value
    changed = evaluate_universe_expression(source, inputs, listing_dates=DATES, interval="1h")
    short = {
        s: FeatureFrame(f.symbol, f.open_time.iloc[:2], f.values.iloc[:2], f.available.iloc[:2])
        for s, f in inputs.items()
    }
    truncated = evaluate_universe_expression(source, short, listing_dates=DATES, interval="1h")
    for symbol in SYMBOLS:
        np.testing.assert_allclose(
            expected[symbol].values.iloc[:2], changed[symbol].values.iloc[:2], equal_nan=True
        )
        np.testing.assert_allclose(
            expected[symbol].values.iloc[:2], truncated[symbol].values, equal_nan=True
        )
