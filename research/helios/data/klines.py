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
