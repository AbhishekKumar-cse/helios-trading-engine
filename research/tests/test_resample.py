"""Tests for resampling and comparing bars (step 055)."""

import numpy as np
import pandas as pd
import pytest

from helios.data.klines import KlineFormatError, interval_us
from helios.data.resample import compare_bars, compared_count, resample_bars

MINUTE = interval_us("1m")
HOUR = interval_us("1h")
START = 1735689600000000  # 2025-01-01 00:00 UTC


def minute_bars(minutes: int = 120, start: int = START) -> pd.DataFrame:
    """Minute bars whose values make the expected hourly answer easy to check."""
    i = np.arange(minutes, dtype="float64")
    return pd.DataFrame(
        {
            "open_time": start + np.arange(minutes) * MINUTE,
            "open": 100.0 + i,
            "high": 110.0 + i,
            "low": 90.0 + i,
            "close": 105.0 + i,
            "volume": np.ones(minutes),
            "close_time": start + np.arange(1, minutes + 1) * MINUTE - 1,
            "quote_volume": np.full(minutes, 2.0),
            "trades": np.full(minutes, 3, dtype="int64"),
            "taker_buy_base": np.full(minutes, 0.5),
            "taker_buy_quote": np.full(minutes, 1.0),
        }
    )


def test_two_hours_from_120_minutes() -> None:
    hours = resample_bars(minute_bars(120), "1m", "1h")
    assert len(hours) == 2
    assert hours["open_time"].tolist() == [START, START + HOUR]


def test_open_high_low_close_follow_the_rules() -> None:
    first = resample_bars(minute_bars(120), "1m", "1h").iloc[0]
    assert first["open"] == 100.0  # first minute's open
    assert first["close"] == 105.0 + 59  # last minute's close
    assert first["high"] == 110.0 + 59  # highest minute
    assert first["low"] == 90.0  # lowest minute


def test_volumes_and_trades_are_added_up() -> None:
    first = resample_bars(minute_bars(120), "1m", "1h").iloc[0]
    assert first["volume"] == 60.0
    assert first["quote_volume"] == 120.0
    assert first["trades"] == 180
    assert first["taker_buy_base"] == 30.0
    assert first["close_time"] == START + HOUR - 1


def test_incomplete_hour_is_left_out() -> None:
    """A missing minute could hide the real high or low, so that hour is not reported."""
    bars = minute_bars(120).drop(index=5)
    hours = resample_bars(bars, "1m", "1h")
    assert len(hours) == 1
    assert hours["open_time"].iloc[0] == START + HOUR


def test_incomplete_hour_can_be_kept_on_purpose() -> None:
    bars = minute_bars(120).drop(index=5)
    hours = resample_bars(bars, "1m", "1h", require_complete=False)
    assert len(hours) == 2
    assert hours["bars_used"].tolist() == [59, 60]


def test_unsorted_input_is_handled() -> None:
    shuffled = minute_bars(60).sample(frac=1, random_state=0)
    assert resample_bars(shuffled, "1m", "1h").iloc[0]["open"] == 100.0


def test_shorter_target_is_rejected() -> None:
    with pytest.raises(KlineFormatError, match="not longer than"):
        resample_bars(minute_bars(60), "1h", "1m")


def test_uneven_intervals_are_rejected() -> None:
    with pytest.raises(KlineFormatError, match="does not divide evenly"):
        resample_bars(minute_bars(60), "8h", "12h")


def test_empty_input_is_rejected() -> None:
    with pytest.raises(KlineFormatError, match="no bars to resample"):
        resample_bars(minute_bars(60).head(0), "1m", "1h")


# ---------------------------------------------------------------- comparing


def test_identical_bars_have_no_mismatches() -> None:
    hours = resample_bars(minute_bars(120), "1m", "1h")
    assert compare_bars(hours, hours.copy()).empty
    assert compared_count(hours, hours) == 2


def test_a_changed_value_is_reported() -> None:
    hours = resample_bars(minute_bars(120), "1m", "1h")
    other = hours.copy()
    other.loc[1, "high"] = 999.0
    problems = compare_bars(hours, other)
    assert len(problems) == 1
    row = problems.iloc[0]
    assert row["column"] == "high"
    assert row["open_time"] == START + HOUR
    assert row["right"] == 999.0


def test_several_columns_can_differ() -> None:
    hours = resample_bars(minute_bars(120), "1m", "1h")
    other = hours.copy()
    other.loc[0, ["open", "volume"]] = [1.0, 2.0]
    assert set(compare_bars(hours, other)["column"]) == {"open", "volume"}


def test_tiny_rounding_differences_are_allowed() -> None:
    """Adding up 60 small numbers can differ in the last bits; that is not a mismatch."""
    hours = resample_bars(minute_bars(120), "1m", "1h")
    other = hours.copy()
    other["volume"] = other["volume"] * (1 + 1e-15)
    assert compare_bars(hours, other).empty


def test_only_shared_timestamps_are_compared() -> None:
    hours = resample_bars(minute_bars(180), "1m", "1h")
    assert compared_count(hours, hours.head(2)) == 2
    assert compare_bars(hours, hours.head(2)).empty


def test_no_shared_timestamps_is_rejected() -> None:
    hours = resample_bars(minute_bars(120), "1m", "1h")
    later = resample_bars(minute_bars(120, START + 10 * HOUR), "1m", "1h")
    with pytest.raises(KlineFormatError, match="share no timestamps"):
        compare_bars(hours, later)
