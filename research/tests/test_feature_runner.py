"""Tests for the feature runner (step 071).

Test features are declared into a private registry, so the project's real feature set is
untouched. The last few tests run on the committed fixture bars.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from helios.data.klines import interval_us, normalise_klines, read_klines
from helios.features.registry import FeatureError, FeatureRegistry, Units, feature
from helios.features.runner import FeatureFrame, check_bars, compute_features

HOUR = interval_us("1h")
START = 1735689600000000  # 2025-01-01 00:00 UTC
FIXTURES = Path(__file__).parent / "fixtures"


def bars(n: int = 10, start: int = START, step: int = HOUR) -> pd.DataFrame:
    """Simple hourly bars whose close is 100, 101, 102, ..."""
    return pd.DataFrame(
        {
            "open_time": [start + i * step for i in range(n)],
            "open": [100.0 + i for i in range(n)],
            "high": [100.5 + i for i in range(n)],
            "low": [99.5 + i for i in range(n)],
            "close": [100.0 + i for i in range(n)],
            "volume": [1.0] * n,
        }
    )


@pytest.fixture
def registry() -> FeatureRegistry:
    """Two features: one needing a single bar, one needing four."""
    reg = FeatureRegistry()

    @feature(name="close_price", lookback=1, units=Units.PRICE, registry=reg)
    def close_price(frame: pd.DataFrame) -> pd.Series:
        """The closing price of the bar."""
        return frame["close"]

    @feature(name="change_over_3", lookback=4, units=Units.PRICE, registry=reg)
    def change_over_3(frame: pd.DataFrame) -> pd.Series:
        """Close now minus the close three bars ago."""
        return frame["close"] - frame["close"].shift(3)

    return reg


# ---------------------------------------------------------------- shape and values


def test_values_and_mask_have_the_same_shape(registry: FeatureRegistry) -> None:
    result = compute_features(bars(), "1h", registry=registry, symbol="TESTUSDT")
    assert isinstance(result, FeatureFrame)
    assert result.values.shape == result.available.shape == (10, 2)
    assert result.names == ["change_over_3", "close_price"]
    assert result.symbol == "TESTUSDT"


def test_the_values_are_the_ones_the_feature_computed(registry: FeatureRegistry) -> None:
    result = compute_features(bars(), "1h", registry=registry)
    assert result.values["close_price"].tolist() == [100.0 + i for i in range(10)]
    assert result.values["change_over_3"].iloc[3] == 3.0  # 103 - 100


def test_only_the_asked_features_are_computed(registry: FeatureRegistry) -> None:
    result = compute_features(bars(), "1h", names=["close_price"], registry=registry)
    assert result.names == ["close_price"]


def test_the_timestamp_is_kept_beside_the_values(registry: FeatureRegistry) -> None:
    result = compute_features(bars(), "1h", registry=registry)
    assert result.open_time.iloc[0] == START
    assert len(result.open_time) == result.rows


# ---------------------------------------------------------------- warm-up


def test_warmup_rows_are_unavailable(registry: FeatureRegistry) -> None:
    """A feature looking back 4 bars cannot have a value on the first 3."""
    result = compute_features(bars(), "1h", registry=registry)
    mask = result.available["change_over_3"]
    assert mask.tolist()[:3] == [False, False, False]
    assert mask.tolist()[3:] == [True] * 7


def test_unavailable_values_are_nan_never_zero(registry: FeatureRegistry) -> None:
    """Zero would claim 'nothing moved'; NaN says 'we do not know'."""
    result = compute_features(bars(), "1h", registry=registry)
    warm_up = result.values["change_over_3"].iloc[:3]
    assert warm_up.isna().all()
    assert (warm_up == 0).sum() == 0


def test_a_single_bar_feature_is_available_at_once(registry: FeatureRegistry) -> None:
    result = compute_features(bars(), "1h", registry=registry)
    assert result.available["close_price"].all()


def test_the_first_usable_row_is_reported(registry: FeatureRegistry) -> None:
    result = compute_features(bars(), "1h", registry=registry)
    assert result.first_usable_row() == 3  # once the slowest feature is ready


def test_usable_drops_the_warm_up_rows(registry: FeatureRegistry) -> None:
    result = compute_features(bars(), "1h", registry=registry)
    usable = result.usable()
    assert len(usable) == 7
    assert list(usable.columns) == ["open_time", "change_over_3", "close_price"]
    assert usable["open_time"].iloc[0] == START + 3 * HOUR


def test_availability_is_reported_per_feature(registry: FeatureRegistry) -> None:
    result = compute_features(bars(), "1h", registry=registry)
    share = result.availability()
    assert share["close_price"] == 1.0
    assert share["change_over_3"] == pytest.approx(0.7)


# ---------------------------------------------------------------- gaps in the bars


def test_a_window_spanning_a_gap_is_unavailable(registry: FeatureRegistry) -> None:
    """The real reason this matters: BTC is missing 170 hours, 75 of them in one outage."""
    with_gap = bars(10).drop(index=5).reset_index(drop=True)
    result = compute_features(with_gap, "1h", registry=registry)
    mask = result.available["change_over_3"].tolist()
    # hours present: 0 1 2 3 4 6 7 8 9, so the gap is the missing hour 5
    assert mask[:3] == [False, False, False]  # warm-up
    assert mask[3] and mask[4]  # windows still entirely before the gap
    assert mask[5:8] == [False, False, False]  # windows that span the gap
    assert mask[8]  # far enough past the gap again


def test_a_single_bar_feature_is_unaffected_by_gaps(registry: FeatureRegistry) -> None:
    with_gap = bars(10).drop(index=5).reset_index(drop=True)
    result = compute_features(with_gap, "1h", registry=registry)
    assert result.available["close_price"].all()


def test_values_across_a_gap_are_blanked(registry: FeatureRegistry) -> None:
    with_gap = bars(10).drop(index=5).reset_index(drop=True)
    result = compute_features(with_gap, "1h", registry=registry)
    assert result.values["change_over_3"].iloc[5:8].isna().all()
    assert not result.values["change_over_3"].iloc[4] != result.values["change_over_3"].iloc[4]


# ---------------------------------------------------------------- values that are not numbers


def test_a_feature_returning_nan_is_unavailable_there() -> None:
    reg = FeatureRegistry()

    @feature(name="sometimes_missing", lookback=1, units=Units.RATIO, registry=reg)
    def sometimes_missing(frame: pd.DataFrame) -> pd.Series:
        """Missing on the third bar, on purpose."""
        values = frame["close"].copy()
        values.iloc[2] = np.nan
        return values

    result = compute_features(bars(5), "1h", registry=reg)
    assert result.available["sometimes_missing"].tolist() == [True, True, False, True, True]


def test_an_infinite_value_is_unavailable() -> None:
    reg = FeatureRegistry()

    @feature(name="divides_by_zero", lookback=1, units=Units.RATIO, registry=reg)
    def divides_by_zero(frame: pd.DataFrame) -> pd.Series:
        """Produces infinity on the second bar."""
        values = frame["close"].copy()
        values.iloc[1] = np.inf
        return values

    result = compute_features(bars(4), "1h", registry=reg)
    assert result.available["divides_by_zero"].tolist() == [True, False, True, True]


def test_a_feature_returning_the_wrong_length_is_refused() -> None:
    reg = FeatureRegistry()

    @feature(name="too_short", lookback=1, units=Units.RATIO, registry=reg)
    def too_short(frame: pd.DataFrame) -> pd.Series:
        """Returns fewer values than there are bars."""
        return frame["close"].iloc[:3]

    with pytest.raises(FeatureError, match="one value per bar"):
        compute_features(bars(10), "1h", registry=reg)


# ---------------------------------------------------------------- bad input


def test_missing_columns_are_refused(registry: FeatureRegistry) -> None:
    with pytest.raises(FeatureError, match="missing columns"):
        compute_features(bars().drop(columns=["volume"]), "1h", registry=registry)


def test_no_bars_are_refused(registry: FeatureRegistry) -> None:
    with pytest.raises(FeatureError, match="no bars"):
        compute_features(bars(0), "1h", registry=registry)


def test_unsorted_bars_are_refused(registry: FeatureRegistry) -> None:
    """Shuffled bars would let a window reach forward in time."""
    shuffled = bars().sample(frac=1, random_state=0)
    with pytest.raises(FeatureError, match="sorted oldest first"):
        compute_features(shuffled, "1h", registry=registry)


def test_duplicate_timestamps_are_refused(registry: FeatureRegistry) -> None:
    doubled = pd.concat([bars(3), bars(3)]).sort_values("open_time").reset_index(drop=True)
    with pytest.raises(FeatureError, match="duplicate timestamps"):
        compute_features(doubled, "1h", registry=registry)


def test_off_grid_timestamps_are_refused(registry: FeatureRegistry) -> None:
    """Like the 43 real candles from February 2018 that start at 09:28:14.789."""
    odd = bars()
    odd.loc[2, "open_time"] += 1_694_789_000
    with pytest.raises(FeatureError, match="not on the 1h grid"):
        compute_features(odd, "1h", registry=registry)


def test_several_coins_at_once_are_refused(registry: FeatureRegistry) -> None:
    mixed = bars(4)
    mixed["symbol"] = ["BTCUSDT", "BTCUSDT", "ETHUSDT", "ETHUSDT"]
    with pytest.raises(FeatureError, match="several coins"):
        compute_features(mixed, "1h", registry=registry)


def test_an_empty_registry_is_refused() -> None:
    with pytest.raises(FeatureError, match="no features are declared"):
        compute_features(bars(), "1h", registry=FeatureRegistry())


# ---------------------------------------------------------------- on the real fixture bars


def test_it_runs_on_the_committed_fixture(registry: FeatureRegistry) -> None:
    real = normalise_klines(read_klines(FIXTURES / "BTCUSDT-1h-2024-12.zip"))
    result = compute_features(real, "1h", names=["close_price"], registry=registry)
    assert result.rows == 3
    assert result.available["close_price"].all()
    assert result.values["close_price"].iloc[0] == pytest.approx(96340.60)


def test_the_symbol_is_taken_from_the_bars(registry: FeatureRegistry) -> None:
    real = normalise_klines(read_klines(FIXTURES / "BTCUSDT-1h-2024-12.zip"))
    real["symbol"] = "BTCUSDT"
    result = compute_features(real, "1h", names=["close_price"], registry=registry)
    assert result.symbol == "BTCUSDT"


def test_check_bars_accepts_the_fixture() -> None:
    real = normalise_klines(read_klines(FIXTURES / "BTCUSDT-1h-2025-01.zip"))
    check_bars(real, "1h")  # must not raise
