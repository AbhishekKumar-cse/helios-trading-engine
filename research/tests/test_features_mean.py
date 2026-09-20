"""Tests for the distance-from-average features (step 073).

The prices are chosen so the answers are exact fractions that can be checked on paper:

- eleven bars at 100 then one at 110, over a 12-bar window: the average is
  (11 x 100 + 110) / 12 = 1210 / 12, so the value is 110 / (1210/12) - 1 = 12/11 - 1 = **1/11**;
- prices 1, 2, ..., 12: the average is 6.5, so the value is 12 / 6.5 - 1 = **11/13**;
- a flat price is exactly **0** above its own average.
"""

import pandas as pd
import pytest

from helios.data.klines import interval_us
from helios.features.basic import (
    close_over_mean_12,
    close_over_mean_48,
    close_over_mean_168,
    distance_from_mean,
)
from helios.features.registry import REGISTRY, Units
from helios.features.runner import compute_features

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


# ---------------------------------------------------------------- hand-calculated values


def test_a_flat_price_is_exactly_on_its_average() -> None:
    values = distance_from_mean(pd.Series([100.0] * 12), 12)
    assert values.iloc[11] == 0.0


def test_eleven_flat_bars_then_a_jump() -> None:
    """Average = 1210/12, so 110 is 12/11 of it: the answer is exactly 1/11."""
    closes = [100.0] * 11 + [110.0]
    values = distance_from_mean(pd.Series(closes), 12)
    assert values.iloc[11] == pytest.approx(1 / 11)
    assert values.iloc[11] == pytest.approx(0.09090909090909091)


def test_a_straight_ramp() -> None:
    """Prices 1..12 average 6.5, so the last bar is 12/6.5 - 1 = 11/13 above it."""
    values = distance_from_mean(pd.Series([float(i) for i in range(1, 13)]), 12)
    assert values.iloc[11] == pytest.approx(11 / 13)
    assert values.iloc[11] == pytest.approx(0.8461538461538463)


def test_a_price_below_its_average_is_negative() -> None:
    closes = [100.0] * 11 + [90.0]
    values = distance_from_mean(pd.Series(closes), 12)
    assert values.iloc[11] == pytest.approx(90 / (1190 / 12) - 1)
    assert values.iloc[11] < 0


def test_a_window_of_one_is_always_zero() -> None:
    """The average of a single bar is that bar, so the distance is always nothing."""
    values = distance_from_mean(pd.Series([100.0, 250.0, 3.0]), 1)
    assert values.tolist() == [0.0, 0.0, 0.0]


# ---------------------------------------------------------------- warm-up and bad input


def test_the_window_must_be_full_first() -> None:
    values = distance_from_mean(pd.Series([100.0] * 15), 12)
    assert values.iloc[:11].isna().all()
    assert not values.iloc[11:].isna().any()


def test_a_zero_price_run_gives_nan() -> None:
    values = distance_from_mean(pd.Series([0.0] * 12), 12)
    assert values.isna().all()


def test_a_window_below_one_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one bar"):
        distance_from_mean(pd.Series([100.0, 101.0]), 0)


# ---------------------------------------------------------------- only the past is used


def test_a_later_price_cannot_change_an_earlier_value() -> None:
    """The window is trailing: what happens after bar 12 cannot touch bar 12."""
    closes = [100.0] * 11 + [110.0]
    before = distance_from_mean(pd.Series(closes), 12).iloc[11]

    with_future = distance_from_mean(pd.Series([*closes, 10_000.0, 0.01]), 12).iloc[11]
    assert with_future == pytest.approx(before)


# ---------------------------------------------------------------- how they are declared


def test_the_three_features_are_registered() -> None:
    for name in ("close_over_mean_12", "close_over_mean_48", "close_over_mean_168"):
        assert name in REGISTRY


def test_each_one_declares_its_window_as_the_lookback() -> None:
    """A 12-bar average depends on 12 bars, so 11 earlier ones must exist first."""
    assert (
        REGISTRY.get("close_over_mean_12").lookback,
        REGISTRY.get("close_over_mean_12").warmup,
    ) == (12, 11)
    assert (
        REGISTRY.get("close_over_mean_48").lookback,
        REGISTRY.get("close_over_mean_48").warmup,
    ) == (48, 47)
    assert (
        REGISTRY.get("close_over_mean_168").lookback,
        REGISTRY.get("close_over_mean_168").warmup,
    ) == (168, 167)


def test_they_are_fractions() -> None:
    for name in ("close_over_mean_12", "close_over_mean_48", "close_over_mean_168"):
        assert REGISTRY.get(name).units is Units.FRACTION


def test_the_functions_can_be_called_directly() -> None:
    frame = bars_from([100.0] * 11 + [110.0])
    assert close_over_mean_12(frame).iloc[11] == pytest.approx(1 / 11)
    assert close_over_mean_48(frame).isna().all()  # only 12 bars
    assert close_over_mean_168(frame).isna().all()


# ---------------------------------------------------------------- through the runner


def test_the_runner_marks_the_warm_up_unavailable() -> None:
    result = compute_features(bars_from([100.0] * 14), "1h", names=["close_over_mean_12"])
    mask = result.available["close_over_mean_12"].tolist()
    assert mask == [False] * 11 + [True] * 3
    assert result.values["close_over_mean_12"].iloc[11] == 0.0


def test_a_gap_blanks_the_windows_that_span_it() -> None:
    """A 12-bar average across a missing hour is not a 12-hour average."""
    frame = bars_from([100.0] * 20).drop(index=12).reset_index(drop=True)
    result = compute_features(frame, "1h", names=["close_over_mean_12"])
    mask = result.available["close_over_mean_12"].tolist()
    assert mask[11]  # the last window entirely before the gap
    assert not any(mask[12:22])  # every window that reaches across it


def test_the_slower_features_need_much_more_history() -> None:
    result = compute_features(
        bars_from([100.0 + i for i in range(200)]),
        "1h",
        names=["close_over_mean_12", "close_over_mean_48", "close_over_mean_168"],
    )
    assert result.first_usable_row() == 167  # the weekly average decides
    share = result.availability()
    assert share["close_over_mean_12"] > share["close_over_mean_168"]
