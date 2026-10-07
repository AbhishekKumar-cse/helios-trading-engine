"""Step 081 acceptance: unavailable until full history, across the real feature set."""

import numpy as np
import pandas as pd
import pytest

from helios.data.klines import interval_us
from helios.features import basic  # noqa: F401 -- register the production features
from helios.features.helpers import rank_ts, zscore
from helios.features.registry import REGISTRY, FeatureRegistry, Units, feature
from helios.features.runner import compute_features

START = 1735689600000000


def bars(n: int, interval: str = "1h") -> pd.DataFrame:
    """Synthetic varying observations for tests, not market or research results."""
    t = np.arange(n)
    price = 100 + 0.1 * t + np.sin(t)
    volume = 10.0 + t % 7
    return pd.DataFrame(
        {
            "open_time": START + t * interval_us(interval),
            "open": price,
            "high": price + 2,
            "low": price - 2,
            "close": price + 0.2 * np.sin(0.7 * t),
            "volume": volume,
            "quote_volume": volume * price,
            "taker_buy_base": volume * (0.2 + 0.1 * (t % 6)),
            "trades": 1 + t % 11,
        }
    )


@pytest.mark.parametrize("name", REGISTRY.names())
def test_each_registered_feature_masks_its_exact_warmup(name: str) -> None:
    spec = REGISTRY.get(name)
    frame = bars(spec.warmup + 2)
    # Large index labels must not be mistaken for already-observed history.
    frame.index = pd.Index(np.arange(len(frame)) + 1000)
    result = compute_features(frame, "1h", names=[name])
    assert result.values[name].iloc[: spec.warmup].isna().all()
    assert not result.available[name].iloc[: spec.warmup].any()
    assert result.available[name].iloc[spec.warmup :].all()
    assert np.isfinite(result.values[name].iloc[spec.warmup :]).all()
    assert result.first_usable_row() == spec.warmup
    assert result.usable()["open_time"].iloc[0] == frame["open_time"].iloc[spec.warmup]
    if spec.warmup:
        short = compute_features(frame.iloc[: spec.warmup], "1h", names=[name])
        assert short.values[name].isna().all()
        assert not short.available[name].any()
        assert short.first_usable_row() is None
        assert short.usable().empty


@pytest.mark.parametrize(("lookback", "warmup"), [(1, 0), (4, 3), (4, 6)])
def test_runner_masks_finite_early_values_and_retains_valid_zero(
    lookback: int, warmup: int
) -> None:
    registry = FeatureRegistry()

    @feature(
        name="finite_early", lookback=lookback, warmup=warmup, units=Units.RATIO, registry=registry
    )
    def finite_early(frame: pd.DataFrame) -> pd.Series:
        """Deliberately emit zeros before enough observations exist."""
        return pd.Series(0.0, index=frame.index)

    result = compute_features(bars(warmup + 2), "1h", registry=registry)
    assert result.available["finite_early"].tolist() == [False] * warmup + [True, True]
    assert result.values["finite_early"].iloc[:warmup].isna().all()
    assert result.values["finite_early"].iloc[warmup:].tolist() == [0.0, 0.0]


@pytest.mark.parametrize("invalid", [np.nan, np.inf, -np.inf])
def test_full_history_does_not_make_nonfinite_boundary_value_available(invalid: float) -> None:
    registry = FeatureRegistry()

    @feature(name="invalid_boundary", lookback=3, units=Units.RATIO, registry=registry)
    def invalid_boundary(frame: pd.DataFrame) -> pd.Series:
        """Emit an invalid number just as the history becomes long enough."""
        values = pd.Series(1.0, index=frame.index)
        values.iloc[2] = invalid
        return values

    result = compute_features(bars(4), "1h", registry=registry)
    assert result.available["invalid_boundary"].tolist() == [False, False, False, True]
    assert result.values["invalid_boundary"].iloc[:3].isna().all()


@pytest.mark.parametrize("name", ["helper_zscore", "helper_rank"])
def test_step_080_helpers_integrate_with_runner_mask(name: str) -> None:
    registry = FeatureRegistry()
    operator = zscore if name == "helper_zscore" else rank_ts

    @feature(name=name, lookback=4, units=Units.DIMENSIONLESS, registry=registry)
    def helper_feature(frame: pd.DataFrame) -> pd.Series:
        """Apply a trailing operator to bar volume."""
        return operator(frame["volume"], 4)

    result = compute_features(bars(5), "1h", registry=registry)
    assert result.available[name].tolist() == [False, False, False, True, True]
    assert result.values[name].iloc[:3].isna().all()
    expected = 1.161895003862225 if name == "helper_zscore" else 1.0
    assert result.values[name].iloc[3] == pytest.approx(expected)


@pytest.mark.parametrize("interval", ["1h", "1m"])
def test_combined_features_keep_individual_masks_and_align_usable_rows(interval: str) -> None:
    frame = bars(175, interval)
    result = compute_features(frame, interval)
    # volatility_168 needs 169 closes; 168-bar z-scores need only 168 rows.
    assert result.available["volume_zscore_168"].iloc[167]
    assert not result.available["volatility_168"].iloc[167]
    assert result.first_usable_row() == 168
    pd.testing.assert_series_equal(
        result.usable()["open_time"], frame["open_time"].iloc[168:].reset_index(drop=True)
    )
    assert result.available["hour_of_day_sin"].all()
    assert result.values.where(~result.available).isna().all().all()


def test_new_input_slice_must_rewarm_without_hidden_history() -> None:
    frame = bars(200)
    whole = compute_features(frame, "1h", names=["log_return_24"])
    assert whole.available["log_return_24"].iloc[100]
    sliced = compute_features(frame.iloc[100:130], "1h", names=["log_return_24"])
    assert not sliced.available["log_return_24"].iloc[:24].any()
    assert sliced.values["log_return_24"].iloc[:24].isna().all()
    assert sliced.available["log_return_24"].iloc[24:].all()
