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

import math

import numpy as np
import pandas as pd

from helios.features.helpers import zscore
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


# ---------------------------------------------------------------- distance from the average


def distance_from_mean(close: pd.Series, window: int) -> pd.Series:
    """How far the close sits above or below its own average of the last `window` bars.

        close / mean(close over the last `window` bars, this one included) - 1

    0.02 means the price is 2 % above its recent average. The window is **trailing**: it
    ends at the current bar and never includes a later one, so the value at any moment could
    have been computed at that moment.

    Two of these on different windows say something a single price cannot: 2 % above the
    12-bar average but 5 % below the 168-bar average is a short bounce inside a longer fall.
    """
    if window < 1:
        raise ValueError(f"an average needs at least one bar, got {window}")

    prices = pd.to_numeric(close, errors="coerce").astype("float64")
    average = prices.rolling(window).mean()
    ratio = (prices / average).where(average > 0)
    return pd.Series(ratio - 1.0, index=close.index, dtype="float64")


@feature(name="close_over_mean_12", lookback=12, units=Units.FRACTION)
def close_over_mean_12(bars: pd.DataFrame) -> pd.Series:
    """Distance from the average of the last 12 bars: half a day on hourly bars."""
    return distance_from_mean(bars["close"], 12)


@feature(name="close_over_mean_48", lookback=48, units=Units.FRACTION)
def close_over_mean_48(bars: pd.DataFrame) -> pd.Series:
    """Distance from the average of the last 48 bars: two days on hourly bars."""
    return distance_from_mean(bars["close"], 48)


@feature(name="close_over_mean_168", lookback=168, units=Units.FRACTION)
def close_over_mean_168(bars: pd.DataFrame) -> pd.Series:
    """Distance from the average of the last 168 bars: a week on hourly bars."""
    return distance_from_mean(bars["close"], 168)


# ---------------------------------------------------------------- volatility

PARKINSON_FACTOR = 1.0 / (4.0 * math.log(2.0))
GARMAN_KLASS_FACTOR = 2.0 * math.log(2.0) - 1.0


def realized_volatility(close: pd.Series, window: int) -> pd.Series:
    """Standard deviation of the 1-bar log returns over the last `window` bars.

    The plainest measure of how much a price is moving. It uses closes only, so everything
    that happened inside a bar — a spike up and back down — is invisible to it. That is the
    weakness the two estimators below address.
    """
    if window < 2:
        raise ValueError(f"a standard deviation needs at least two returns, got {window}")
    returns = log_return(close, 1)
    return returns.rolling(window).std(ddof=1)


def _log_ratio(top: pd.Series, bottom: pd.Series) -> pd.Series:
    """ln(top / bottom), or NaN where either price is not positive."""
    high = pd.to_numeric(top, errors="coerce").astype("float64")
    low = pd.to_numeric(bottom, errors="coerce").astype("float64")
    ratio = (high / low).where((high > 0) & (low > 0))
    return pd.Series(np.log(ratio), index=top.index, dtype="float64")


def parkinson(high: pd.Series, low: pd.Series, window: int) -> pd.Series:
    """Parkinson's volatility estimator (1980), from the high and low of each bar.

        sqrt( mean( ln(high/low)^2 ) / (4 ln 2) )

    A bar that swings from 100 up to 110 and back to 100 has a close-to-close return of
    zero, so the plain measure calls it a quiet bar. Parkinson sees the 10 % range and calls
    it what it was. For the same number of bars it is several times more accurate than
    close-to-close, which matters when only 24 bars are in the window.

    It assumes the price wanders without drift and that trading never stops, so it tends to
    read slightly low on real data. It is an estimate, not a measurement.
    """
    if window < 1:
        raise ValueError(f"an estimate needs at least one bar, got {window}")
    squared = _log_ratio(high, low) ** 2
    estimate = np.sqrt(PARKINSON_FACTOR * squared.rolling(window).mean())
    return pd.Series(estimate, index=high.index, dtype="float64")


def garman_klass(
    open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series, window: int
) -> pd.Series:
    """Garman–Klass volatility estimator (1980), from all four prices of each bar.

        sqrt( mean( 0.5 * ln(high/low)^2 - (2 ln 2 - 1) * ln(close/open)^2 ) )

    It adds the open-to-close move to Parkinson's range, which makes it more accurate again.

    The subtraction cannot make the term negative for a real bar: the coefficient
    2 ln 2 - 1 = 0.386 is smaller than 0.5, and a close can never be further from the open
    than the high is from the low. The guard below is therefore only for impossible input
    (a close outside the bar's own range), where the answer is NaN rather than a made-up
    number.
    """
    if window < 1:
        raise ValueError(f"an estimate needs at least one bar, got {window}")
    range_part = 0.5 * _log_ratio(high, low) ** 2
    move_part = GARMAN_KLASS_FACTOR * _log_ratio(close, open_) ** 2
    average = (range_part - move_part).rolling(window).mean()
    estimate = np.sqrt(average.where(average >= 0))
    return pd.Series(estimate, index=close.index, dtype="float64")


@feature(name="volatility_24", lookback=25, units=Units.VOLATILITY)
def volatility_24(bars: pd.DataFrame) -> pd.Series:
    """Standard deviation of the last 24 one-bar log returns: a day on hourly bars."""
    return realized_volatility(bars["close"], 24)


@feature(name="volatility_168", lookback=169, units=Units.VOLATILITY)
def volatility_168(bars: pd.DataFrame) -> pd.Series:
    """Standard deviation of the last 168 one-bar log returns: a week on hourly bars."""
    return realized_volatility(bars["close"], 168)


@feature(name="parkinson_24", lookback=24, units=Units.VOLATILITY)
def parkinson_24(bars: pd.DataFrame) -> pd.Series:
    """Parkinson volatility over 24 bars, using each bar's high and low."""
    return parkinson(bars["high"], bars["low"], 24)


@feature(name="garman_klass_24", lookback=24, units=Units.VOLATILITY)
def garman_klass_24(bars: pd.DataFrame) -> pd.Series:
    """Garman-Klass volatility over 24 bars, using open, high, low and close."""
    return garman_klass(bars["open"], bars["high"], bars["low"], bars["close"], 24)


# ---------------------------------------------------------------- activity


def rolling_zscore(values: pd.Series, window: int) -> pd.Series:
    """How unusual each value is, measured against its own last `window` values.

        (value - mean of the window) / standard deviation of the window

    A z-score of 2 means "twice as far above the recent average as the usual wobble". This
    is what makes volume comparable: 900 BTC traded in an hour is enormous for a quiet
    market and ordinary for a busy one, and the raw number cannot tell the difference.

    A window with no variation at all has no scale to measure against, so the answer is NaN
    rather than zero or infinity.
    """
    if window < 2:
        raise ValueError(f"a z-score needs at least two values, got {window}")
    return zscore(values, window)


@feature(name="volume_zscore_168", lookback=168, units=Units.ZSCORE)
def volume_zscore_168(bars: pd.DataFrame) -> pd.Series:
    """How unusual this bar's traded amount is, against the last week of bars."""
    return rolling_zscore(bars["volume"], 168)


@feature(name="dollar_volume", lookback=1, units=Units.NOTIONAL)
def dollar_volume(bars: pd.DataFrame) -> pd.Series:
    """Money that changed hands in this bar, in the quote currency (USDT).

    Taken from the exchange's own `quote_volume`, which is the sum of price x quantity over
    the real trades in the bar. Computing `close x volume` instead would use one price for
    the whole bar and quietly misstate a bar that moved.
    """
    return pd.to_numeric(bars["quote_volume"], errors="coerce").astype("float64")


@feature(name="dollar_volume_zscore_168", lookback=168, units=Units.ZSCORE)
def dollar_volume_zscore_168(bars: pd.DataFrame) -> pd.Series:
    """How unusual this bar's money flow is, against the last week of bars."""
    return rolling_zscore(pd.to_numeric(bars["quote_volume"], errors="coerce"), 168)


@feature(name="taker_buy_ratio", lookback=1, units=Units.RATIO)
def taker_buy_ratio(bars: pd.DataFrame) -> pd.Series:
    """Share of this bar's base volume bought by takers (step 077).

    `taker_buy_base / volume` is 0 for all taker sells, 0.5 for balanced flow, and 1
    for all taker buys. Both amounts must use the base currency, not quote volume.
    A bar without trades has no ratio. Missing, nonfinite or impossible amounts are
    also NaN, never clipped into a plausible observation.
    """
    bought = pd.to_numeric(bars["taker_buy_base"], errors="coerce").astype("float64")
    total = pd.to_numeric(bars["volume"], errors="coerce").astype("float64")
    valid = np.isfinite(bought) & np.isfinite(total) & (total > 0) & (bought >= 0)
    valid &= bought <= total
    return pd.Series(bought.where(valid) / total.where(valid), index=bars.index, dtype="float64")


@feature(name="taker_buy_ratio_zscore_168", lookback=168, units=Units.ZSCORE)
def taker_buy_ratio_zscore_168(bars: pd.DataFrame) -> pd.Series:
    """Taker-buy ratio against its last 168 bars, including the current bar.

    Uses sample standard deviation, like the other activity z-scores. A full window
    of valid ratios is required; a constant window has no scale and stays unavailable.
    The window is in bars: a week on hourly data, 168 minutes on minute data.
    """
    return rolling_zscore(taker_buy_ratio(bars), 168)


def _trade_counts(bars: pd.DataFrame) -> pd.Series:
    """Read the canonical `trades` column; invalid counts remain unknown."""
    counts = pd.to_numeric(bars["trades"], errors="coerce").astype("float64")
    valid = np.isfinite(counts) & (counts >= 0) & (counts == counts.round())
    return counts.where(valid)


@feature(name="n_trades_zscore_168", lookback=168, units=Units.ZSCORE)
def n_trades_zscore_168(bars: pd.DataFrame) -> pd.Series:
    """Trade count against the last 168 bars, including this bar (step 078).

    The source column is `trades`. Zero trades is a valid observation; negative,
    fractional, missing or nonfinite counts are unavailable. Uses sample standard
    deviation and requires a full, varying window, like the other activity z-scores.
    """
    return rolling_zscore(_trade_counts(bars), 168)


@feature(name="average_trade_size", lookback=1, units=Units.VOLUME)
def average_trade_size(bars: pd.DataFrame) -> pd.Series:
    """Base-currency volume per trade in this bar: volume / trades (step 078).

    For BTCUSDT the unit is BTC per trade, not USDT. With no trades the average is
    undefined, not zero. Invalid volume or trade counts also produce NaN.
    """
    counts = _trade_counts(bars)
    volume = pd.to_numeric(bars["volume"], errors="coerce").astype("float64")
    valid = np.isfinite(volume) & (volume >= 0) & (counts > 0)
    return pd.Series(volume.where(valid) / counts.where(valid), index=bars.index, dtype="float64")


# ---------------------------------------------------------------- calendar


def _calendar_phase(bars: pd.DataFrame, *, weekday: bool) -> pd.Series:
    """UTC opening-time phase in radians, from integer microsecond timestamps.

    Use discrete hour/day categories: minutes do not change the hour encoding, and
    hours do not change the weekday encoding. Monday is day 0. Missing or out-of-range
    timestamps become NaN rather than a fabricated calendar observation.
    """
    timestamps = pd.to_datetime(bars["open_time"], unit="us", utc=True, errors="coerce")
    component = timestamps.dt.dayofweek if weekday else timestamps.dt.hour
    period = 7 if weekday else 24
    return component.astype("float64") * (2 * math.pi / period)


@feature(name="hour_of_day_sin", lookback=1, units=Units.DIMENSIONLESS)
def hour_of_day_sin(bars: pd.DataFrame) -> pd.Series:
    """sin(2*pi*UTC opening hour/24); pairs with hour_of_day_cos (step 079)."""
    return pd.Series(np.sin(_calendar_phase(bars, weekday=False)), index=bars.index)


@feature(name="hour_of_day_cos", lookback=1, units=Units.DIMENSIONLESS)
def hour_of_day_cos(bars: pd.DataFrame) -> pd.Series:
    """cos(2*pi*UTC opening hour/24); keeps hours 23 and 0 adjacent (step 079)."""
    return pd.Series(np.cos(_calendar_phase(bars, weekday=False)), index=bars.index)


@feature(name="day_of_week_sin", lookback=1, units=Units.DIMENSIONLESS)
def day_of_week_sin(bars: pd.DataFrame) -> pd.Series:
    """sin(2*pi*UTC opening weekday/7), Monday=0 through Sunday=6 (step 079)."""
    return pd.Series(np.sin(_calendar_phase(bars, weekday=True)), index=bars.index)


@feature(name="day_of_week_cos", lookback=1, units=Units.DIMENSIONLESS)
def day_of_week_cos(bars: pd.DataFrame) -> pd.Series:
    """cos(2*pi*UTC opening weekday/7); pairs with day_of_week_sin (step 079)."""
    return pd.Series(np.cos(_calendar_phase(bars, weekday=True)), index=bars.index)
