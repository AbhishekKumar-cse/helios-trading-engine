"""Taker-buy flow features (step 077): arithmetic, availability and causality."""

import math

import numpy as np
import pandas as pd
import pytest

from helios.data.klines import interval_us
from helios.features.basic import taker_buy_ratio, taker_buy_ratio_zscore_168
from helios.features.registry import REGISTRY, Units
from helios.features.runner import compute_features

NAMES = ["taker_buy_ratio", "taker_buy_ratio_zscore_168"]
START = 1735689600000000  # 2025-01-01 00:00 UTC


def bars_from(ratios: list[float], interval: str = "1h") -> pd.DataFrame:
    """Valid bars with varying volume, so a ratio cannot be confused with raw flow."""
    n = len(ratios)
    volume = np.arange(1, n + 1, dtype="float64") * 4
    return pd.DataFrame(
        {
            "open_time": [START + i * interval_us(interval) for i in range(n)],
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "volume": volume,
            "taker_buy_base": volume * ratios,
            # Deliberately different quote-currency ratio: do not use these fields.
            "quote_volume": volume * 100,
            "taker_buy_quote": volume * 10,
        }
    )


def test_ratio_measures_base_volume_share_including_endpoints() -> None:
    frame = bars_from([0.0, 0.25, 0.5, 0.75, 1.0])
    frame.index = pd.Index([10, 20, 30, 40, 50], name="bar")
    result = taker_buy_ratio(frame)
    assert result.tolist() == [0.0, 0.25, 0.5, 0.75, 1.0]
    pd.testing.assert_index_equal(result.index, frame.index)
    assert result.dtype == np.dtype("float64")


def test_numeric_text_is_supported_without_changing_input() -> None:
    frame = pd.DataFrame({"volume": ["10", "20"], "taker_buy_base": ["2.5", "15"]})
    original = frame.copy(deep=True)
    assert taker_buy_ratio(frame).tolist() == [0.25, 0.75]
    pd.testing.assert_frame_equal(frame, original)


@pytest.mark.parametrize(
    ("volume", "bought"),
    [
        (0.0, 0.0),
        (0.0, 1.0),
        (-4.0, -1.0),
        (4.0, -1.0),
        (4.0, 5.0),
        (np.nan, 1.0),
        (4.0, np.nan),
        (np.inf, 1.0),
        (4.0, np.inf),
        (-np.inf, 1.0),
        (4.0, -np.inf),
        ("bad", 1.0),
        (4.0, "bad"),
    ],
)
def test_invalid_amounts_are_unavailable_not_clipped(volume: object, bought: object) -> None:
    frame = bars_from([0.5]).astype({"volume": object, "taker_buy_base": object})
    frame.loc[0, ["volume", "taker_buy_base"]] = [volume, bought]
    assert taker_buy_ratio(frame).isna().all()
    result = compute_features(frame, "1h", names=[NAMES[0]])
    assert not result.available[NAMES[0]].any()
    assert result.values[NAMES[0]].isna().all()


def test_declarations_match_the_amount_of_history_needed() -> None:
    raw = REGISTRY.get(NAMES[0])
    score = REGISTRY.get(NAMES[1])
    assert (raw.lookback, raw.warmup, raw.units) == (1, 0, Units.RATIO)
    assert (score.lookback, score.warmup, score.units) == (168, 167, Units.ZSCORE)


@pytest.mark.parametrize("direction", [1, -1])
def test_zscore_matches_hand_calculated_balanced_window(direction: int) -> None:
    """84 each of .25 and .75: mean=.5, sample variance=168*.25**2/167."""
    ratios = [0.25, 0.75] * 84
    if direction < 0:
        ratios.reverse()
    values = taker_buy_ratio_zscore_168(bars_from(ratios))
    assert values.iloc[:167].isna().all()
    assert values.iloc[167] == pytest.approx(direction * math.sqrt(167 / 168))


@pytest.mark.parametrize("interval", ["1h", "1m"])
def test_runner_warms_up_in_bars_not_hours(interval: str) -> None:
    result = compute_features(bars_from([0.25, 0.75] * 100, interval), interval, names=NAMES)
    assert result.available[NAMES[0]].all()
    assert not result.available[NAMES[1]].iloc[:167].any()
    assert result.available[NAMES[1]].iloc[167:].all()
    assert result.first_usable_row() == 167


def test_constant_ratio_is_valid_but_has_no_zscore() -> None:
    # Volume varies: the z-score must describe ratios, not taker-buy amounts.
    result = compute_features(bars_from([0.5] * 200), "1h", names=NAMES)
    assert result.available[NAMES[0]].all()
    assert (result.values[NAMES[0]] == 0.5).all()
    assert not result.available[NAMES[1]].any()
    assert result.values[NAMES[1]].isna().all()


@pytest.mark.parametrize("bad_bar", ["zero_volume", "missing_taker", "above_total"])
def test_invalid_bar_invalidates_its_entire_window_then_recovers(bad_bar: str) -> None:
    frame = bars_from([0.25, 0.75] * 200)
    if bad_bar == "zero_volume":
        frame.loc[180, ["volume", "taker_buy_base"]] = 0.0
    elif bad_bar == "missing_taker":
        frame.loc[180, "taker_buy_base"] = np.nan
    else:
        frame.loc[180, "taker_buy_base"] = frame.loc[180, "volume"] + 1.0
    result = compute_features(frame, "1h", names=NAMES)
    assert not result.available[NAMES[0]].iloc[180]
    assert result.available[NAMES[0]].iloc[181:].all()
    assert result.available[NAMES[1]].iloc[167:180].all()
    assert not result.available[NAMES[1]].iloc[180:348].any()
    assert result.values[NAMES[1]].iloc[180:348].isna().all()
    assert result.available[NAMES[1]].iloc[348:].all()


def test_gap_masks_only_windows_that_cross_it() -> None:
    frame = bars_from([0.25, 0.75] * 200).drop(index=180).reset_index(drop=True)
    result = compute_features(frame, "1h", names=NAMES)
    assert result.available[NAMES[0]].all()
    assert result.available[NAMES[1]].iloc[167:180].all()
    assert not result.available[NAMES[1]].iloc[180:347].any()
    assert result.values[NAMES[1]].iloc[180:347].isna().all()
    assert result.available[NAMES[1]].iloc[347:].all()


@pytest.mark.parametrize("cut", [0, 166, 167, 199])
def test_future_changes_cannot_rewrite_past_values_or_availability(cut: int) -> None:
    rng = np.random.default_rng(77)
    frame = bars_from(rng.uniform(0, 1, 240).tolist())
    original = frame.copy(deep=True)
    before = compute_features(frame, "1h", names=NAMES)
    pd.testing.assert_frame_equal(frame, original)
    altered = frame.copy(deep=True)
    altered.loc[cut + 1 :, "volume"] = 1000.0
    altered.loc[cut + 1 :, "taker_buy_base"] = 999.0
    after = compute_features(altered, "1h", names=NAMES)
    prefix = compute_features(frame.iloc[: cut + 1], "1h", names=NAMES)
    pd.testing.assert_frame_equal(before.values.iloc[: cut + 1], after.values.iloc[: cut + 1])
    pd.testing.assert_frame_equal(before.available.iloc[: cut + 1], after.available.iloc[: cut + 1])
    pd.testing.assert_frame_equal(before.values.iloc[: cut + 1], prefix.values)
    pd.testing.assert_frame_equal(before.available.iloc[: cut + 1], prefix.available)
