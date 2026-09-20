"""Build longer bars from shorter ones, and compare two sets of bars (step 055).

Used as a cross-check: minute bars resampled to hours must match the hourly files Binance
publishes. The two come from different files, so agreement is real evidence that the
download, the timestamp handling and the Parquet build are all correct.

Rules for one output bar:

    open   = first bar's open        volume, quote_volume, trades, taker_* = sums
    high   = highest high            close_time = last bar's close_time
    low    = lowest low              open_time  = start of the period
    close  = last bar's close

An output bar is only produced from a **complete** period. If minutes are missing, the high
or low could be wrong, so that period is left out rather than quietly reported as a bar.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from helios.data.klines import KlineFormatError, interval_us

SUM_COLUMNS = ("volume", "quote_volume", "trades", "taker_buy_base", "taker_buy_quote")
COMPARE_COLUMNS = ("open", "high", "low", "close", *SUM_COLUMNS)


def resample_bars(
    frame: pd.DataFrame,
    from_interval: str,
    to_interval: str,
    *,
    require_complete: bool = True,
) -> pd.DataFrame:
    """Combine bars of `from_interval` into bars of `to_interval`.

    With `require_complete` (the default), a period is only returned when every smaller bar
    inside it is present.
    """
    small = interval_us(from_interval)
    large = interval_us(to_interval)
    if large <= small:
        raise KlineFormatError(f"{to_interval} is not longer than {from_interval}")
    if large % small:
        raise KlineFormatError(f"{from_interval} does not divide evenly into {to_interval}")
    if frame.empty:
        raise KlineFormatError("no bars to resample")

    ordered = frame.sort_values("open_time")
    period = (ordered["open_time"] // large) * large

    grouped = ordered.groupby(period, sort=True)
    out = grouped.agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        close_time=("close_time", "last"),
        quote_volume=("quote_volume", "sum"),
        trades=("trades", "sum"),
        taker_buy_base=("taker_buy_base", "sum"),
        taker_buy_quote=("taker_buy_quote", "sum"),
        bars_used=("open", "size"),
    )
    out.index.name = "open_time"
    out = out.reset_index()

    if require_complete:
        out = out.loc[out["bars_used"] == large // small].reset_index(drop=True)
    return out


def compare_bars(
    left: pd.DataFrame,
    right: pd.DataFrame,
    columns: tuple[str, ...] = COMPARE_COLUMNS,
    relative_tolerance: float = 1e-9,
) -> pd.DataFrame:
    """Rows where two sets of bars disagree, one line per differing value.

    Only timestamps present in both are compared. Sums of many small numbers can differ in
    the last bits, so the comparison allows a tiny relative difference; prices are expected
    to match exactly.
    """
    shared = left.merge(right, on="open_time", suffixes=("_left", "_right"))
    if shared.empty:
        raise KlineFormatError("the two sets of bars share no timestamps")

    problems = []
    for column in columns:
        a = shared[f"{column}_left"].to_numpy(dtype="float64")
        b = shared[f"{column}_right"].to_numpy(dtype="float64")
        differs = ~np.isclose(a, b, rtol=relative_tolerance, atol=0.0, equal_nan=True)
        if differs.any():
            problems.append(
                pd.DataFrame(
                    {
                        "open_time": shared.loc[differs, "open_time"].to_numpy(),
                        "column": column,
                        "left": a[differs],
                        "right": b[differs],
                        "difference": a[differs] - b[differs],
                    }
                )
            )

    if not problems:
        return pd.DataFrame(columns=["open_time", "column", "left", "right", "difference"])
    return pd.concat(problems, ignore_index=True).sort_values(["open_time", "column"])


def compared_count(left: pd.DataFrame, right: pd.DataFrame) -> int:
    """How many timestamps the two sets have in common (the size of the check)."""
    return len(set(left["open_time"]) & set(right["open_time"]))
