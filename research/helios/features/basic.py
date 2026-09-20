"""The first features: log returns over 1, 4 and 24 bars (step 072).

A **log return** is the natural logarithm of a price ratio:

    r = ln(close_now / close_n_bars_ago)

Why logarithms rather than plain percentage changes:

1. **They add up.** Four 1-bar log returns sum exactly to the 4-bar log return. Percentage
   changes do not: +10 % then -10 % is -1 %, not 0 %.
2. **They are symmetric.** A rise and the fall that undoes it are the same size with opposite
   signs, so an average is not quietly biased upwards.
3. **They suit the maths later.** Sharpe, volatility and most of the statistics assume
   something close to additive, roughly symmetric returns.

Each feature uses only the current close and one earlier close, so nothing can reach into
the future. The window is counted in **bars**, not hours: on hourly bars `log_return_24`
covers a day, on minute bars it covers 24 minutes.

Importing this module registers the features in the project registry.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from helios.features.registry import Units, feature


def log_return(close: pd.Series, bars: int) -> pd.Series:
    """Log return over `bars` bars: ln(close_now / close_`bars`_ago).

    Prices at or below zero give NaN rather than an error or a made-up number; the runner
    then marks those rows unavailable. Binance prices are always positive, but a feature
    should not assume its input is perfect.
    """
    if bars < 1:
        raise ValueError(f"a return needs at least one bar, got {bars}")

    now = pd.to_numeric(close, errors="coerce").astype("float64")
    before = now.shift(bars)
    ratio = (now / before).where((now > 0) & (before > 0))
    return pd.Series(np.log(ratio), index=close.index, dtype="float64")


@feature(name="log_return_1", lookback=2, units=Units.LOG_RETURN)
def log_return_1(bars: pd.DataFrame) -> pd.Series:
    """Log return over the previous bar: the shortest move the data can show."""
    return log_return(bars["close"], 1)


@feature(name="log_return_4", lookback=5, units=Units.LOG_RETURN)
def log_return_4(bars: pd.DataFrame) -> pd.Series:
    """Log return over 4 bars: a short trend, quieter than a single bar."""
    return log_return(bars["close"], 4)


@feature(name="log_return_24", lookback=25, units=Units.LOG_RETURN)
def log_return_24(bars: pd.DataFrame) -> pd.Series:
    """Log return over 24 bars: one day on hourly bars."""
    return log_return(bars["close"], 24)
