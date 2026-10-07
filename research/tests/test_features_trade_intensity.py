"""Step 078: trade-count intensity and average base quantity per trade."""

import math

import numpy as np
import pandas as pd
import pytest

from helios.data.klines import interval_us
from helios.features.basic import average_trade_size, n_trades_zscore_168
from helios.features.registry import REGISTRY, Units
from helios.features.runner import compute_features

NAMES = ["n_trades_zscore_168", "average_trade_size"]
START = 1735689600000000


def bars_from(counts: list[float], interval: str = "1h") -> pd.DataFrame:
    n = len(counts)
    return pd.DataFrame(
        {
            "open_time": [START + i * interval_us(interval) for i in range(n)],
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "volume": np.asarray(counts) * 2.5,
            "quote_volume": np.asarray(counts) * 250.0,
            "trades": counts,
        }
    )


def test_average_uses_base_volume_and_preserves_index_and_input() -> None:
    frame = bars_from([2, 4, 5])
    frame["volume"] = [5.0, 20.0, 1.0]
    frame.index = pd.Index([10, 20, 30], name="bar")
    original = frame.copy(deep=True)
    result = average_trade_size(frame)
    assert result.tolist() == [2.5, 5.0, 0.2]
    pd.testing.assert_index_equal(result.index, frame.index)
    pd.testing.assert_frame_equal(frame, original)


def test_numeric_text_is_supported() -> None:
    frame = bars_from([2, 4])
    frame["trades"] = ["2", "4"]
    frame["volume"] = ["5", "20"]
    assert average_trade_size(frame).tolist() == [2.5, 5.0]


@pytest.mark.parametrize("direction", [1, -1])
def test_count_zscore_has_hand_calculated_value(direction: int) -> None:
    # 84 zeros and 84 twos: mean=1, sample variance=168/167.
    counts = [0, 2] * 84
    if direction < 0:
        counts.reverse()
    values = n_trades_zscore_168(bars_from(counts))
    assert values.iloc[:167].isna().all()
    assert values.iloc[167] == pytest.approx(direction * math.sqrt(167 / 168))


@pytest.mark.parametrize("interval", ["1h", "1m"])
def test_runner_warmup_and_units(interval: str) -> None:
    result = compute_features(bars_from([1, 3] * 100, interval), interval, names=NAMES)
    assert not result.available[NAMES[0]].iloc[:167].any()
    assert result.available[NAMES[0]].iloc[167:].all()
    assert result.available[NAMES[1]].all()
    assert (result.values[NAMES[1]] == 2.5).all()
    assert result.first_usable_row() == 167
    score, size = (REGISTRY.get(name) for name in NAMES)
    assert (score.lookback, score.warmup, score.units) == (168, 167, Units.ZSCORE)
    assert (size.lookback, size.warmup, size.units) == (1, 0, Units.VOLUME)


def test_zero_trades_is_known_count_but_unknown_average() -> None:
    result = compute_features(bars_from([2, 0] * 84), "1h", names=NAMES)
    assert result.available[NAMES[0]].iloc[-1]
    assert result.values[NAMES[0]].iloc[-1] == pytest.approx(-math.sqrt(167 / 168))
    assert result.available[NAMES[1]].tolist() == [True, False] * 84
    assert result.values[NAMES[1]].iloc[1::2].isna().all()


@pytest.mark.parametrize("count", [0, 5])
def test_constant_count_has_no_zscore_even_when_volume_varies(count: int) -> None:
    frame = bars_from([count] * 200)
    frame["volume"] = np.arange(200, dtype="float64")
    result = compute_features(frame, "1h", names=[NAMES[0]])
    assert not result.available[NAMES[0]].any()
    assert result.values[NAMES[0]].isna().all()


@pytest.mark.parametrize("invalid", [-1, 1.5, np.nan, np.inf, -np.inf, "bad"])
def test_invalid_count_masks_window_and_recovers(invalid: object) -> None:
    frame = bars_from([1, 3] * 200).astype({"trades": object})
    frame.loc[180, "trades"] = invalid
    result = compute_features(frame, "1h", names=NAMES)
    assert result.available[NAMES[0]].iloc[167:180].all()
    assert not result.available[NAMES[0]].iloc[180:348].any()
    assert result.values[NAMES[0]].iloc[180:348].isna().all()
    assert result.available[NAMES[0]].iloc[348:].all()
    assert not result.available[NAMES[1]].iloc[180]
    assert result.available[NAMES[1]].iloc[181:].all()


@pytest.mark.parametrize("invalid", [-1, np.nan, np.inf, -np.inf, "bad"])
def test_invalid_volume_does_not_change_count_intensity(invalid: object) -> None:
    frame = bars_from([1, 3] * 84).astype({"volume": object})
    frame.loc[167, "volume"] = invalid
    result = compute_features(frame, "1h", names=NAMES)
    assert result.available[NAMES[0]].iloc[-1]
    assert not result.available[NAMES[1]].iloc[-1]
    assert pd.isna(result.values[NAMES[1]].iloc[-1])


def test_gap_invalidates_only_count_windows_spanning_it() -> None:
    frame = bars_from([1, 3] * 200).drop(index=180).reset_index(drop=True)
    result = compute_features(frame, "1h", names=NAMES)
    assert result.available[NAMES[0]].iloc[167:180].all()
    assert not result.available[NAMES[0]].iloc[180:347].any()
    assert result.values[NAMES[0]].iloc[180:347].isna().all()
    assert result.available[NAMES[0]].iloc[347:].all()
    assert result.available[NAMES[1]].all()


@pytest.mark.parametrize("cut", [0, 166, 167, 199])
def test_future_changes_and_truncation_leave_past_unchanged(cut: int) -> None:
    frame = bars_from(np.random.default_rng(78).integers(0, 100, 240).tolist())
    before = compute_features(frame, "1h", names=NAMES)
    altered = frame.copy(deep=True)
    altered.loc[cut + 1 :, "trades"] = 1000
    altered.loc[cut + 1 :, "volume"] = 10.0
    after = compute_features(altered, "1h", names=NAMES)
    prefix = compute_features(frame.iloc[: cut + 1], "1h", names=NAMES)
    pd.testing.assert_frame_equal(before.values.iloc[: cut + 1], after.values.iloc[: cut + 1])
    pd.testing.assert_frame_equal(before.available.iloc[: cut + 1], after.available.iloc[: cut + 1])
    pd.testing.assert_frame_equal(before.values.iloc[: cut + 1], prefix.values)
    pd.testing.assert_frame_equal(before.available.iloc[: cut + 1], prefix.available)
