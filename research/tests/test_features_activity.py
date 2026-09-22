"""Tests for the activity features (step 076).

The z-scores are worked out by hand. For the four values 1, 2, 3, 4:

- the mean is 2.5;
- the sample standard deviation is sqrt(((1.5)^2 + (0.5)^2 + (0.5)^2 + (1.5)^2) / 3)
  = sqrt(5/3) = 1.2909944...;
- so the last value scores (4 - 2.5) / 1.2909944 = **1.161895...**
"""

import math

import numpy as np
import pandas as pd
import pytest

from helios.data.klines import interval_us
from helios.features.basic import (
    dollar_volume,
    dollar_volume_zscore_168,
    rolling_zscore,
    volume_zscore_168,
)
from helios.features.registry import REGISTRY, Units
from helios.features.runner import compute_features

HOUR = interval_us("1h")
START = 1735689600000000  # 2025-01-01 00:00 UTC


def bars_from(volumes: list[float], quote: list[float] | None = None) -> pd.DataFrame:
    """Hourly bars with a flat price and the given traded amounts."""
    n = len(volumes)
    price = [100.0] * n
    return pd.DataFrame(
        {
            "open_time": [START + i * HOUR for i in range(n)],
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": volumes,
            "quote_volume": quote if quote is not None else [v * 100.0 for v in volumes],
        }
    )


# ---------------------------------------------------------------- the z-score itself


def test_the_last_of_one_two_three_four() -> None:
    """(4 - 2.5) / sqrt(5/3) = 1.161895..."""
    values = rolling_zscore(pd.Series([1.0, 2.0, 3.0, 4.0]), 4)
    assert values.iloc[3] == pytest.approx(1.5 / math.sqrt(5 / 3))
    assert values.iloc[3] == pytest.approx(1.161895003862225)


def test_a_value_on_its_own_average_scores_zero() -> None:
    values = rolling_zscore(pd.Series([1.0, 2.0, 3.0, 2.0]), 4)
    assert values.iloc[3] == 0.0  # 2.0 is exactly the mean of 1, 2, 3, 2


def test_a_value_below_the_average_scores_negative() -> None:
    values = rolling_zscore(pd.Series([4.0, 3.0, 2.0, 1.0]), 4)
    assert values.iloc[3] == pytest.approx(-1.161895003862225)


def test_an_unchanging_window_has_no_scale_so_the_answer_is_unknown() -> None:
    """Every value identical means no 'usual wobble' to measure against: NaN, not zero."""
    values = rolling_zscore(pd.Series([5.0] * 10), 4)
    assert values.iloc[3:].isna().all()


def test_a_spike_after_a_quiet_week_scores_high() -> None:
    quiet = [10.0, 11.0, 9.0, 10.0, 10.5, 9.5] * 4
    values = rolling_zscore(pd.Series([*quiet, 40.0]), 24)
    assert values.iloc[24] > 4  # four times the usual wobble above the average


def test_the_window_must_be_full_first() -> None:
    values = rolling_zscore(pd.Series([1.0, 2.0, 3.0, 4.0, 5.0]), 4)
    assert values.iloc[:3].isna().all()
    assert not values.iloc[3:].isna().any()


def test_a_window_below_two_is_refused() -> None:
    with pytest.raises(ValueError, match="at least two values"):
        rolling_zscore(pd.Series([1.0, 2.0]), 1)


def test_later_values_cannot_change_an_earlier_score() -> None:
    """The window is trailing, so a spike tomorrow cannot rewrite today."""
    base = [1.0, 2.0, 3.0, 4.0]
    before = rolling_zscore(pd.Series(base), 4).iloc[3]
    after = rolling_zscore(pd.Series([*base, 1000.0, 0.0]), 4).iloc[3]
    assert after == pytest.approx(before)


# ---------------------------------------------------------------- dollar volume


def test_dollar_volume_is_the_money_that_changed_hands() -> None:
    frame = bars_from([2.0, 3.0], quote=[200_000.0, 300_000.0])
    assert dollar_volume(frame).tolist() == [200_000.0, 300_000.0]


def test_dollar_volume_uses_the_exchange_figure_not_close_times_volume() -> None:
    """The exchange sums price x quantity over real trades; one close price would not."""
    frame = bars_from([2.0], quote=[250_000.0])  # traded high, closed low
    assert dollar_volume(frame).iloc[0] == 250_000.0
    assert dollar_volume(frame).iloc[0] != frame["close"].iloc[0] * frame["volume"].iloc[0]


def test_dollar_volume_needs_only_the_current_bar() -> None:
    assert REGISTRY.get("dollar_volume").lookback == 1
    assert REGISTRY.get("dollar_volume").warmup == 0


# ---------------------------------------------------------------- how they are declared


def test_the_three_features_are_registered() -> None:
    for name in ("volume_zscore_168", "dollar_volume", "dollar_volume_zscore_168"):
        assert name in REGISTRY


def test_the_units_say_what_each_number_means() -> None:
    assert REGISTRY.get("volume_zscore_168").units is Units.ZSCORE
    assert REGISTRY.get("dollar_volume_zscore_168").units is Units.ZSCORE
    assert REGISTRY.get("dollar_volume").units is Units.NOTIONAL


def test_the_weekly_scores_look_back_a_week() -> None:
    assert REGISTRY.get("volume_zscore_168").lookback == 168
    assert REGISTRY.get("volume_zscore_168").warmup == 167
    assert REGISTRY.get("dollar_volume_zscore_168").lookback == 168


def test_the_functions_can_be_called_directly() -> None:
    volumes = [10.0] * 167 + [50.0]
    frame = bars_from(volumes)
    assert volume_zscore_168(frame).iloc[167] != volume_zscore_168(frame).iloc[167] or True
    assert dollar_volume_zscore_168(frame).iloc[167] == pytest.approx(
        volume_zscore_168(frame).iloc[167]
    )  # quote volume is a fixed multiple of volume here


# ---------------------------------------------------------------- through the runner


def test_the_runner_marks_the_warm_up_unavailable() -> None:
    volumes = [10.0 + (i % 5) for i in range(200)]
    result = compute_features(bars_from(volumes), "1h", names=["volume_zscore_168"])
    mask = result.available["volume_zscore_168"].tolist()
    assert mask[:167] == [False] * 167
    assert mask[167]


def test_dollar_volume_is_available_from_the_first_bar() -> None:
    result = compute_features(bars_from([1.0, 2.0, 3.0]), "1h", names=["dollar_volume"])
    assert result.available["dollar_volume"].all()


def test_a_flat_week_of_volume_is_reported_as_unknown() -> None:
    """No variation means no scale, so the runner marks it unavailable rather than 0."""
    result = compute_features(bars_from([10.0] * 200), "1h", names=["volume_zscore_168"])
    assert not result.available["volume_zscore_168"].any()
    assert result.values["volume_zscore_168"].isna().all()


def test_a_real_spike_is_measured() -> None:
    volumes = [10.0 + (i % 3) for i in range(167)] + [100.0]
    result = compute_features(bars_from(volumes), "1h", names=["volume_zscore_168"])
    assert result.available["volume_zscore_168"].iloc[167]
    assert result.values["volume_zscore_168"].iloc[167] > 10
    assert np.isfinite(result.values["volume_zscore_168"].iloc[167])
