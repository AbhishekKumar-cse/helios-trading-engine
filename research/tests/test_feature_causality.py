"""Step 082: changing or removing the future cannot rewrite feature history.

Collected by the default pytest command, including CI. Parametrization comes from
the registry so new registered features inherit this contract. Synthetic valid bars
cover every currently required source column; extend the generator for new inputs.
"""

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from helios.data.klines import interval_us
from helios.features import basic  # noqa: F401 -- populate the production registry
from helios.features.registry import REGISTRY, FeatureRegistry, Units, feature
from helios.features.runner import compute_features

START = 1735689600000000


def synthetic_bars(n: int, seed: int, interval: str) -> pd.DataFrame:
    """Finite, varying OHLCV test data, never presented as market observations."""
    rng = np.random.default_rng(seed)
    opening = rng.uniform(90.0, 110.0, n)
    closing = opening + rng.uniform(-2.0, 2.0, n)
    volume = rng.uniform(10.0, 100.0, n)
    bought = volume * rng.uniform(0.1, 0.9, n)
    times = START + np.arange(n) * interval_us(interval)
    return pd.DataFrame(
        {
            "open_time": times,
            "close_time": times + interval_us(interval) - 1,
            "open": opening,
            "high": np.maximum(opening, closing) + 1,
            "low": np.minimum(opening, closing) - 1,
            "close": closing,
            "volume": volume,
            "quote_volume": volume * (opening + closing) / 2,
            "trades": rng.integers(1, 1000, n),
            "taker_buy_base": bought,
            "taker_buy_quote": bought * (opening + closing) / 2,
        }
    )


def replace_future(frame: pd.DataFrame, cut: int, seed: int, interval: str) -> pd.DataFrame:
    """Replace every numeric future column, retaining valid bars and time order."""
    changed = frame.copy(deep=True)
    future = synthetic_bars(len(frame) - cut - 1, seed + 1, interval)
    for column in ("open", "high", "low", "close"):
        future[column] *= 100
    for column in ("volume", "taker_buy_base"):
        future[column] *= 10
    for column in ("quote_volume", "taker_buy_quote"):
        future[column] *= 1000
    future["trades"] += 1000
    # Shift both calendar coordinates as well as introducing a future-only gap.
    future["open_time"] = frame["open_time"].iloc[cut + 1 :].to_numpy() + (
        8 * 24 + 3
    ) * interval_us("1h")
    future["close_time"] = future["open_time"] + interval_us(interval) - 1
    future.index = changed.index[cut + 1 :]
    changed.loc[future.index, :] = future
    pd.testing.assert_frame_equal(changed.iloc[: cut + 1], frame.iloc[: cut + 1])
    return changed


def assert_causal_prefix(
    frame: pd.DataFrame,
    changed: pd.DataFrame,
    cut: int,
    name: str,
    interval: str,
    registry: FeatureRegistry = REGISTRY,
) -> None:
    original = compute_features(frame, interval, names=[name], registry=registry)
    perturbed = compute_features(changed, interval, names=[name], registry=registry)
    truncated = compute_features(frame.iloc[: cut + 1], interval, names=[name], registry=registry)
    for result in (perturbed, truncated):
        pd.testing.assert_frame_equal(
            original.available.iloc[: cut + 1],
            result.available.iloc[: cut + 1],
            check_exact=True,
        )
        pd.testing.assert_frame_equal(
            original.values.iloc[: cut + 1],
            result.values.iloc[: cut + 1],
            check_exact=True,
        )


@pytest.mark.parametrize("name", REGISTRY.names())
@pytest.mark.parametrize("interval", ["1h", "1m"])
@settings(max_examples=30, deadline=None)
@given(seed=st.integers(0, 2**32 - 2), offset=st.integers(0, 40))
def test_every_registered_feature_is_causal(
    name: str, interval: str, seed: int, offset: int
) -> None:
    spec = REGISTRY.get(name)
    cut = spec.warmup + offset
    frame = synthetic_bars(spec.warmup + 50, seed, interval)
    original = compute_features(frame, interval, names=[name])
    # Check a usable output, not just two identically masked warm-up prefixes.
    assert original.available[name].iloc[cut], f"{name}: no usable value at cut {cut}"
    changed = replace_future(frame, cut, seed, interval)
    assert_causal_prefix(frame, changed, cut, name, interval)


@pytest.mark.parametrize("leak", ["next_bar", "global_mean", "centered", "availability"])
def test_causality_check_detects_deliberate_future_leaks(leak: str) -> None:
    registry = FeatureRegistry()

    @feature(name="leaking_feature", lookback=3, units=Units.RATIO, registry=registry)
    def leaking_feature(frame: pd.DataFrame) -> pd.Series:
        """Intentionally incorrect feature, confined to a private test registry."""
        if leak == "next_bar":
            return frame["close"].shift(-1)
        if leak == "global_mean":
            return frame["close"] - frame["close"].mean()
        if leak == "centered":
            return frame["close"].rolling(3, center=True).mean()
        # Future-dependent NaN must fail even when finite values otherwise agree.
        if frame["close"].iloc[-1] >= 1000:
            return pd.Series(np.nan, index=frame.index)
        return frame["close"]

    frame = synthetic_bars(20, 82, "1h")
    changed = replace_future(frame, 10, 82, "1h")
    with pytest.raises(AssertionError):
        assert_causal_prefix(frame, changed, 10, "leaking_feature", "1h", registry)
