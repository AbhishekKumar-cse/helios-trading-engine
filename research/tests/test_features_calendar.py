"""Step 079: UTC calendar coordinates, boundaries and timestamp-only causality."""

import math

import numpy as np
import pandas as pd
import pytest

from helios.features.basic import (
    day_of_week_cos,
    day_of_week_sin,
    hour_of_day_cos,
    hour_of_day_sin,
)
from helios.features.registry import REGISTRY, Units
from helios.features.runner import compute_features

NAMES = ["hour_of_day_sin", "hour_of_day_cos", "day_of_week_sin", "day_of_week_cos"]
FUNCTIONS = [hour_of_day_sin, hour_of_day_cos, day_of_week_sin, day_of_week_cos]


def bars_from(dates: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open_time": [pd.Timestamp(date).value // 1000 for date in dates],
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "volume": 1.0,
        }
    )


@pytest.mark.parametrize(
    ("hour", "sine", "cosine"), [(0, 0, 1), (6, 1, 0), (12, 0, -1), (18, -1, 0)]
)
def test_hour_quadrants(hour: int, sine: int, cosine: int) -> None:
    frame = bars_from([f"2025-01-06T{hour:02d}:00:00Z"])
    assert hour_of_day_sin(frame).iloc[0] == pytest.approx(sine, abs=1e-14)
    assert hour_of_day_cos(frame).iloc[0] == pytest.approx(cosine, abs=1e-14)


@pytest.mark.parametrize("weekday", range(7))
def test_weekdays_start_with_monday(weekday: int) -> None:
    frame = bars_from([f"2025-01-{6 + weekday:02d}T00:00:00Z"])
    assert day_of_week_sin(frame).iloc[0] == pytest.approx(math.sin(2 * math.pi * weekday / 7))
    assert day_of_week_cos(frame).iloc[0] == pytest.approx(math.cos(2 * math.pi * weekday / 7))


def test_timestamp_is_utc_not_local_and_uses_open_not_close() -> None:
    # Monday in India is still Sunday at 19:00 UTC.
    frame = bars_from(["2025-01-06T00:30:00+05:30"])
    frame["close_time"] = pd.Timestamp("2025-01-07T12:00:00Z").value // 1000
    assert hour_of_day_sin(frame).iloc[0] == pytest.approx(math.sin(2 * math.pi * 19 / 24))
    assert hour_of_day_cos(frame).iloc[0] == pytest.approx(math.cos(2 * math.pi * 19 / 24))
    assert day_of_week_sin(frame).iloc[0] == pytest.approx(math.sin(2 * math.pi * 6 / 7))


def test_minutes_share_hour_and_hours_share_weekday() -> None:
    frame = bars_from(["2025-01-06T06:00:00Z", "2025-01-06T06:59:00Z", "2025-01-06T23:00:00Z"])
    result = compute_features(frame, "1m", names=NAMES)
    assert result.available.all().all()
    np.testing.assert_allclose(result.values.iloc[0, :2], result.values.iloc[1, :2])
    assert result.values["day_of_week_sin"].tolist() == [0.0] * 3
    assert result.values["day_of_week_cos"].tolist() == [1.0] * 3


def test_wraparound_distance_matches_other_adjacent_categories() -> None:
    frame = bars_from(["2025-01-05T23:00:00Z", "2025-01-06T00:00:00Z", "2025-01-07T01:00:00Z"])
    result = compute_features(frame, "1h", names=NAMES)
    for pair in (NAMES[:2], NAMES[2:]):
        coordinates = result.values[pair].to_numpy()
        wrap_distance = np.linalg.norm(coordinates[1] - coordinates[0])
        next_distance = np.linalg.norm(coordinates[2] - coordinates[1])
        assert wrap_distance == pytest.approx(next_distance)
        np.testing.assert_allclose((coordinates**2).sum(axis=1), 1.0)


@pytest.mark.parametrize(
    ("date", "weekday"),
    [("2024-02-29T00:00:00Z", 3), ("2024-12-31T00:00:00Z", 1), ("2025-01-01T00:00:00Z", 2)],
)
def test_leap_day_and_year_boundary(date: str, weekday: int) -> None:
    frame = bars_from([date])
    assert day_of_week_sin(frame).iloc[0] == pytest.approx(math.sin(2 * math.pi * weekday / 7))
    assert day_of_week_cos(frame).iloc[0] == pytest.approx(math.cos(2 * math.pi * weekday / 7))


def test_no_warmup_or_gap_penalty_and_no_input_mutation() -> None:
    frame = bars_from(["2025-01-06T00:00:00Z", "2025-01-13T00:00:00Z"])
    frame.index = pd.Index([10, 20], name="bar")
    original = frame.copy(deep=True)
    for function in FUNCTIONS:
        values = function(frame)
        pd.testing.assert_index_equal(values.index, frame.index)
        assert values.dtype == np.dtype("float64")
        assert values.iloc[0] == pytest.approx(values.iloc[1])
    result = compute_features(frame, "1h", names=NAMES)
    assert result.available.all().all()
    assert result.first_usable_row() == 0
    for name in NAMES:
        spec = REGISTRY.get(name)
        assert (spec.lookback, spec.warmup, spec.units) == (1, 0, Units.DIMENSIONLESS)
    pd.testing.assert_frame_equal(frame, original)


def test_prices_and_future_bars_cannot_change_calendar_values() -> None:
    frame = bars_from(["2025-01-06T06:00:00Z", "2025-01-06T07:00:00Z"])
    before = compute_features(frame, "1h", names=NAMES)
    changed = frame.copy(deep=True)
    changed[["open", "high", "low", "close", "volume"]] = 999.0
    pd.testing.assert_frame_equal(
        before.values, compute_features(changed, "1h", names=NAMES).values
    )
    changed.loc[1, "open_time"] = pd.Timestamp("2025-03-01T12:00:00Z").value // 1000
    after = compute_features(changed, "1h", names=NAMES)
    prefix = compute_features(frame.iloc[:1], "1h", names=NAMES)
    pd.testing.assert_frame_equal(before.values.iloc[:1], after.values.iloc[:1])
    pd.testing.assert_frame_equal(before.values.iloc[:1], prefix.values)
    pd.testing.assert_frame_equal(before.available.iloc[:1], prefix.available)


def test_missing_timestamp_is_not_a_calendar_observation() -> None:
    frame = pd.DataFrame({"open_time": [np.nan]})
    for function in FUNCTIONS:
        assert function(frame).isna().all()
