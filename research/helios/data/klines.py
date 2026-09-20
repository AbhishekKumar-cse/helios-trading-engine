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


# ---------------------------------------------------------------- checking rows (step 047)

PRICE_COLUMNS = ("open", "high", "low", "close")

_REQUIRED = (*PRICE_COLUMNS, "volume", "quote_volume", "trades", "taker_buy_base")


def _problems(frame: pd.DataFrame) -> dict[str, pd.Series]:
    """Rule name -> True where the row BREAKS that rule."""
    high, low = frame["high"], frame["low"]
    open_, close = frame["open"], frame["close"]
    return {
        "missing value": frame[list(_REQUIRED)].isna().any(axis=1),
        "price not above zero": (frame[list(PRICE_COLUMNS)] <= 0).any(axis=1),
        "high below open or close": (high < open_) | (high < close),
        "low above open or close": (low > open_) | (low > close),
        "high below low": high < low,
        "negative volume": (frame["volume"] < 0) | (frame["quote_volume"] < 0),
        "negative trade count": frame["trades"] < 0,
        "taker volume above total volume": frame["taker_buy_base"] > frame["volume"],
    }


def validate_bars(frame: pd.DataFrame) -> pd.DataFrame:
    """Return the rows that break a rule, with a `problems` column naming which ones.

    Nothing is repaired or removed: a bad candle means the source data is wrong, and quietly
    "fixing" it would invent numbers and hide the problem. The caller decides what to do
    (the pipeline in step 052 writes these rows to a report).

    An empty result (with the same columns) means every row passed.
    """
    missing = [c for c in (*_REQUIRED, "open_time") if c not in frame.columns]
    if missing:
        raise KlineFormatError(f"columns missing for validation: {missing}")

    flags = _problems(frame)
    bad_anywhere = pd.concat(flags.values(), axis=1).any(axis=1)

    out = frame.loc[bad_anywhere].copy()
    out["problems"] = [
        ", ".join(name for name, mask in flags.items() if bool(mask.loc[index]))
        for index in out.index
    ]
    return out


# ---------------------------------------------------------------- gaps and duplicates (048)

INTERVAL_US: dict[str, int] = {
    "1s": 1_000_000,
    "1m": 60_000_000,
    "3m": 180_000_000,
    "5m": 300_000_000,
    "15m": 900_000_000,
    "30m": 1_800_000_000,
    "1h": 3_600_000_000,
    "2h": 7_200_000_000,
    "4h": 14_400_000_000,
    "6h": 21_600_000_000,
    "8h": 28_800_000_000,
    "12h": 43_200_000_000,
    "1d": 86_400_000_000,
}


def interval_us(interval: str) -> int:
    """Length of one candle in microseconds ('1h' -> 3_600_000_000)."""
    try:
        return INTERVAL_US[interval]
    except KeyError:
        raise KlineFormatError(
            f"unknown interval {interval!r}; known: {sorted(INTERVAL_US)}"
        ) from None


def find_duplicates(frame: pd.DataFrame) -> pd.DataFrame:
    """Rows whose `open_time` appears more than once (every copy is returned)."""
    if "open_time" not in frame.columns:
        raise KlineFormatError("column 'open_time' is missing")
    return frame.loc[frame["open_time"].duplicated(keep=False)].copy()


def find_off_grid(frame: pd.DataFrame, interval: str) -> pd.DataFrame:
    """Rows whose `open_time` does not sit on an exact multiple of the interval."""
    step = interval_us(interval)
    if "open_time" not in frame.columns:
        raise KlineFormatError("column 'open_time' is missing")
    return frame.loc[frame["open_time"] % step != 0].copy()


def find_gaps(frame: pd.DataFrame, interval: str) -> pd.DataFrame:
    """Missing candles between the first and last row, as one row per unbroken run.

    Columns: `gap_start`, `gap_end` (open_time of the first and last missing candle, in UTC
    microseconds), `missing` (how many candles), `gap_start_utc`, `gap_end_utc` (readable).

    Nothing is filled in. A missing candle usually means the exchange was down or the pair
    did not trade; inventing a price there would put made-up data into every later result.
    Candles outside the first/last row are not gaps: that is simply where the data ends.
    """
    step = interval_us(interval)
    if "open_time" not in frame.columns:
        raise KlineFormatError("column 'open_time' is missing")
    if frame.empty:
        raise KlineFormatError("no rows to check for gaps")

    times = frame["open_time"].drop_duplicates().sort_values().to_numpy()
    if times.size and (times % step != 0).any():
        raise KlineFormatError(
            f"timestamps are not on the {interval} grid; check them with find_off_grid first"
        )

    diffs = times[1:] - times[:-1]
    breaks = diffs > step
    starts = times[:-1][breaks] + step
    ends = times[1:][breaks] - step
    counts = (diffs[breaks] // step) - 1

    gaps = pd.DataFrame(
        {
            "gap_start": starts.astype("int64"),
            "gap_end": ends.astype("int64"),
            "missing": counts.astype("int64"),
        }
    )
    gaps["gap_start_utc"] = to_utc(gaps["gap_start"])
    gaps["gap_end_utc"] = to_utc(gaps["gap_end"])
    return gaps
