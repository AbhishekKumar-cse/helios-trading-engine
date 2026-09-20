"""Tests for the log-return features (step 072).

The expected numbers are worked out by hand, not read off a run:

- prices that **double** every bar make every 1-bar log return exactly ln 2 = 0.693147...,
  because ln(200/100) = ln 2;
- over 4 such bars the price is 16 times higher, so the 4-bar return is ln 16 = 4 ln 2;
- a price that returns to where it started gives exactly 0, because ln(1) = 0;
- halving gives -ln 2, the same size as doubling with the opposite sign.

`LN2` below is the mathematical constant, so the checks do not depend on the code being
right about anything except the arithmetic.
"""

import math

import numpy as np
import pandas as pd
import pytest

from helios.data.klines import interval_us
from helios.features.basic import log_return, log_return_1, log_return_4, log_return_24
from helios.features.registry import REGISTRY, Units
from helios.features.runner import compute_features

LN2 = 0.6931471805599453  # ln 2, to 16 digits
HOUR = interval_us("1h")
START = 1735689600000000  # 2025-01-01 00:00 UTC


def bars_from(closes: list[float]) -> pd.DataFrame:
    """Hourly bars with the given closing prices."""
    return pd.DataFrame(
        {
            "open_time": [START + i * HOUR for i in range(len(closes))],
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1.0] * len(closes),
        }
    )


def doubling(n: int, start: float = 100.0) -> list[float]:
    """100, 200, 400, 800, ... — every bar doubles."""
    return [start * 2**i for i in range(n)]


# ---------------------------------------------------------------- hand-calculated values


def test_a_doubling_price_gives_ln_two_every_bar() -> None:
    values = log_return(pd.Series(doubling(5)), 1)
    assert values.iloc[0] != values.iloc[0]  # the first bar has nothing before it: NaN
    assert values.iloc[1] == pytest.approx(LN2)
    assert values.iloc[4] == pytest.approx(LN2)


def test_four_doublings_give_ln_sixteen() -> None:
    """100 -> 1600 is 16x, and ln 16 = 4 ln 2 = 2.772588..."""
    values = log_return(pd.Series(doubling(5)), 4)
    assert values.iloc[4] == pytest.approx(4 * LN2)
    assert values.iloc[4] == pytest.approx(math.log(16))
    assert values.iloc[4] == pytest.approx(2.772588722239781)


def test_halving_is_the_opposite_of_doubling() -> None:
    values = log_return(pd.Series([100.0, 50.0]), 1)
    assert values.iloc[1] == pytest.approx(-LN2)


def test_an_unchanged_price_gives_exactly_zero() -> None:
    values = log_return(pd.Series([100.0, 100.0, 100.0]), 1)
    assert values.iloc[1] == 0.0
    assert values.iloc[2] == 0.0


def test_a_round_trip_gives_zero() -> None:
    """Up 25 % then back down to the start: the 2-bar return is 0, not -1 %."""
    values = log_return(pd.Series([100.0, 125.0, 100.0]), 2)
    assert values.iloc[2] == pytest.approx(0.0, abs=1e-15)


def test_a_known_ten_percent_rise() -> None:
    """ln(1.1) = 0.0953101798043249, a number worth recognising."""
    values = log_return(pd.Series([100.0, 110.0]), 1)
    assert values.iloc[1] == pytest.approx(0.0953101798043249)


# ---------------------------------------------------------------- the property that matters


def test_log_returns_add_up() -> None:
    """Four 1-bar returns sum exactly to the 4-bar return. Percentage changes do not."""
    closes = [100.0, 103.0, 99.5, 107.25, 104.0]
    one = log_return(pd.Series(closes), 1)
    four = log_return(pd.Series(closes), 4)
    assert one.iloc[1:5].sum() == pytest.approx(four.iloc[4])


def test_percentage_changes_would_not_add_up() -> None:
    """The reason logs are used. 100 -> 110 -> 99 is +10 % then -10 %.

    Those percentages sum to **zero**, but the price actually fell 1 %. Log returns do not
    have that problem: they sum to exactly the 2-bar log return.
    """
    closes = pd.Series([100.0, 110.0, 99.0])
    percentage = closes.pct_change()
    assert percentage.iloc[1] == pytest.approx(0.10)
    assert percentage.iloc[2] == pytest.approx(-0.10)
    assert percentage.iloc[1] + percentage.iloc[2] == pytest.approx(0.0, abs=1e-12)  # wrong
    assert closes.iloc[2] / closes.iloc[0] - 1 == pytest.approx(-0.01)  # the truth

    one = log_return(closes, 1)
    two = log_return(closes, 2)
    assert one.iloc[1] + one.iloc[2] == pytest.approx(two.iloc[2])  # right
    assert two.iloc[2] == pytest.approx(math.log(0.99))


# ---------------------------------------------------------------- awkward input


def test_a_zero_price_gives_nan_not_an_error() -> None:
    values = log_return(pd.Series([100.0, 0.0, 100.0]), 1)
    assert np.isnan(values.iloc[1])
    assert np.isnan(values.iloc[2])


def test_a_negative_price_gives_nan() -> None:
    values = log_return(pd.Series([100.0, -50.0]), 1)
    assert np.isnan(values.iloc[1])


def test_the_first_bars_are_nan() -> None:
    values = log_return(pd.Series(doubling(6)), 4)
    assert values.iloc[:4].isna().all()
    assert not np.isnan(values.iloc[4])


def test_zero_bars_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one bar"):
        log_return(pd.Series([100.0, 101.0]), 0)


# ---------------------------------------------------------------- how they are declared


def test_the_three_features_are_registered() -> None:
    for name in ("log_return_1", "log_return_4", "log_return_24"):
        assert name in REGISTRY


def test_each_one_declares_the_right_lookback() -> None:
    """A return over n bars depends on n + 1 closes, so it needs n bars of warm-up."""
    assert REGISTRY.get("log_return_1").lookback == 2
    assert REGISTRY.get("log_return_1").warmup == 1
    assert REGISTRY.get("log_return_4").lookback == 5
    assert REGISTRY.get("log_return_4").warmup == 4
    assert REGISTRY.get("log_return_24").lookback == 25
    assert REGISTRY.get("log_return_24").warmup == 24


def test_they_are_all_log_returns() -> None:
    for name in ("log_return_1", "log_return_4", "log_return_24"):
        assert REGISTRY.get(name).units is Units.LOG_RETURN


def test_the_functions_can_still_be_called_directly() -> None:
    frame = bars_from(doubling(3))
    assert log_return_1(frame).iloc[1] == pytest.approx(LN2)
    assert log_return_4(frame).isna().all()  # only 3 bars, so never enough
    assert log_return_24(frame).isna().all()


# ---------------------------------------------------------------- through the runner


def test_the_runner_marks_the_warm_up_unavailable() -> None:
    result = compute_features(bars_from(doubling(6)), "1h", names=["log_return_4"])
    mask = result.available["log_return_4"].tolist()
    assert mask == [False, False, False, False, True, True]
    assert result.values["log_return_4"].iloc[4] == pytest.approx(4 * LN2)


def test_the_runner_computes_all_three_together() -> None:
    result = compute_features(
        bars_from(doubling(30)), "1h", names=["log_return_1", "log_return_4", "log_return_24"]
    )
    assert result.values["log_return_1"].iloc[29] == pytest.approx(LN2)
    assert result.values["log_return_4"].iloc[29] == pytest.approx(4 * LN2)
    assert result.values["log_return_24"].iloc[29] == pytest.approx(24 * LN2)
    assert result.first_usable_row() == 24  # the slowest feature decides


def test_a_gap_blanks_the_window_that_spans_it() -> None:
    """A 4-bar return across a missing hour is not a 4-hour return."""
    frame = bars_from(doubling(10)).drop(index=5).reset_index(drop=True)
    result = compute_features(frame, "1h", names=["log_return_4"])
    mask = result.available["log_return_4"].tolist()
    assert mask[4] is True or mask[4]
    assert not any(mask[5:9])


def test_a_zero_price_is_marked_unavailable_by_the_runner() -> None:
    closes = doubling(6)
    closes[3] = 0.0
    result = compute_features(bars_from(closes), "1h", names=["log_return_1"])
    assert result.available["log_return_1"].tolist() == [False, True, True, False, False, True]
