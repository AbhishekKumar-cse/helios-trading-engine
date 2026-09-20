"""Read Binance monthly kline (candle) zips into a table (step 045).

Each monthly zip holds one CSV with **no header row** and **12 comma-separated columns**
(checked against all 617 files in `data/` on 2026-09-20):

    open_time, open, high, low, close, volume, close_time, quote_volume,
    trades, taker_buy_base, taker_buy_quote, ignore

Values are read exactly as Binance wrote them. In particular `open_time` and `close_time`
are **milliseconds** in files up to 2024-12 and **microseconds** from 2025-01 onwards;
step 046 turns both into one unit. Nothing here repairs or drops rows: checking is
step 047, gaps are step 048.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pandas as pd

COLUMNS = (
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "trades",
    "taker_buy_base",
    "taker_buy_quote",
    "ignore",
)

DTYPES: dict[str, str] = {
    "open_time": "int64",
    "open": "float64",
    "high": "float64",
    "low": "float64",
    "close": "float64",
    "volume": "float64",
    "close_time": "int64",
    "quote_volume": "float64",
    "trades": "int64",
    "taker_buy_base": "float64",
    "taker_buy_quote": "float64",
    "ignore": "float64",
}


class KlineFormatError(Exception):
    """The zip or its CSV does not look like a Binance monthly kline file."""


def read_klines(zip_path: Path | str) -> pd.DataFrame:
    """Read one monthly kline zip into a DataFrame with the 12 named columns.

    The zip is read without being extracted, so nothing is unpacked into the project folder.
    """
    zip_path = Path(zip_path)
    if not zip_path.is_file():
        raise KlineFormatError(f"file not found: {zip_path}")

    try:
        with zipfile.ZipFile(zip_path) as archive:
            members = [m for m in archive.namelist() if m.lower().endswith(".csv")]
            if len(members) != 1:
                raise KlineFormatError(f"{zip_path.name}: expected 1 CSV inside, found {members}")
            with archive.open(members[0]) as handle:
                frame = pd.read_csv(
                    handle,
                    header=None,
                    names=list(COLUMNS),
                    dtype=DTYPES,
                )
    except zipfile.BadZipFile as exc:
        raise KlineFormatError(f"{zip_path.name}: not a valid zip ({exc})") from exc
    except ValueError as exc:  # wrong column count, text where a number belongs, header row
        raise KlineFormatError(f"{zip_path.name}: unexpected CSV content ({exc})") from exc

    if frame.empty:
        raise KlineFormatError(f"{zip_path.name}: contains no rows")
    return frame


# ---------------------------------------------------------------- one time unit (step 046)

US_THRESHOLD = 10**14
"""At or above this value a timestamp is microseconds, below it milliseconds.

As microseconds 1e14 is 1973-03-03; as milliseconds it would be the year 5138. Binance data
starts in 2017, so no real timestamp can fall on the wrong side of this line. Binance wrote
milliseconds up to 2024-12 and microseconds from 2025-01.
"""

MIN_TIMESTAMP_US = 1_230_768_000_000_000  # 2009-01-01, before any crypto exchange data
MAX_TIMESTAMP_US = 4_102_444_800_000_000  # 2100-01-01


def normalise_ts(values: pd.Series) -> pd.Series:
    """Turn a column of Binance timestamps into int64 **UTC microseconds**.

    Milliseconds (before 2025-01) are multiplied by 1000; microseconds are kept. Each value
    is judged on its own, so a column holding both units is still handled correctly.
    """
    if values.empty:
        raise KlineFormatError("no timestamps to normalise")
    if not pd.api.types.is_integer_dtype(values):
        raise KlineFormatError(f"timestamps must be whole numbers, got dtype {values.dtype}")

    as_int = values.astype("int64")
    micros = as_int.where(as_int >= US_THRESHOLD, as_int * 1000).astype("int64")

    outside = ~micros.between(MIN_TIMESTAMP_US, MAX_TIMESTAMP_US)
    if outside.any():
        bad = micros[outside].head(3).tolist()
        raise KlineFormatError(f"timestamps outside 2009-2100 after conversion: {bad}")
    return micros


def normalise_klines(frame: pd.DataFrame) -> pd.DataFrame:
    """Copy of `frame` with `open_time` and `close_time` in UTC microseconds."""
    out = frame.copy()
    for column in ("open_time", "close_time"):
        if column not in out.columns:
            raise KlineFormatError(f"column {column!r} is missing")
        out[column] = normalise_ts(out[column])
    return out


def to_utc(micros: pd.Series) -> pd.Series:
    """UTC timestamps for reading by humans (plots and reports); the stored unit stays int64."""
    return pd.to_datetime(micros, unit="us", utc=True)
