"""Load bars from the Parquet store with DuckDB (step 054).

`build_bars.py` writes one Parquet file per coin, interval and year. DuckDB can query those
files directly, and because the folder names carry the coin and the year
(`symbol=BTCUSDT/year=2019/`), a query for one coin and one year opens only that file
instead of reading the whole store.

    load_bars(["BTCUSDT", "ETHUSDT"], "1h", "2023-01-01", "2023-12-31")

Dates are **UTC and inclusive**: an end date of 2023-12-31 includes all of that day.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from helios.data.bars import BAR_COLUMNS, DEFAULT_OUT_DIR, BarBuildError
from helios.data.klines import interval_us

DAY_US = 86_400_000_000
TimeLike = str | date | datetime | int | np.integer | None


def to_micros(value: TimeLike, *, end: bool = False) -> int | None:
    """Turn a date, datetime or 'YYYY-MM-DD' string into UTC microseconds.

    With `end=True` a plain date means the **last** microsecond of that day, so a range like
    2023-01-01 to 2023-12-31 really covers the whole year.
    """
    if value is None:
        return None
    if isinstance(value, bool):  # bool is an int in Python; never a timestamp
        raise BarBuildError("a timestamp cannot be True or False")
    if isinstance(value, int | np.integer):
        # numpy integers come straight out of a DataFrame column and are NOT Python ints
        return int(value)
    if isinstance(value, str):
        # "2024-12-01" is a day, so it must behave like a date (a whole day when it is the
        # end of a range); "2024-12-01T09:30" is an exact moment
        value = date.fromisoformat(value) if len(value) == 10 else datetime.fromisoformat(value)
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=UTC)
        return int(moment.astimezone(UTC).timestamp() * 1_000_000)
    start_of_day = int(datetime(value.year, value.month, value.day, tzinfo=UTC).timestamp())
    micros = start_of_day * 1_000_000
    return micros + DAY_US - 1 if end else micros


def _year_of(micros: int) -> int:
    return datetime.fromtimestamp(micros / 1_000_000, tz=UTC).year


def load_bars(
    symbols: Sequence[str] | str,
    interval: str,
    start: TimeLike = None,
    end: TimeLike = None,
    out_dir: Path = DEFAULT_OUT_DIR,
) -> pd.DataFrame:
    """Bars for one or more coins, oldest first, with a `symbol` column.

    `start` and `end` are UTC and inclusive; leave them out for the whole history.
    """
    interval_us(interval)  # reject an unknown interval before touching the disk
    wanted = [symbols] if isinstance(symbols, str) else list(symbols)
    if not wanted:
        raise BarBuildError("give at least one symbol")

    root = out_dir / "source=binance" / f"interval={interval}"
    if not root.is_dir():
        raise BarBuildError(f"no bars for interval {interval} under {out_dir}")

    first = to_micros(start)
    last = to_micros(end, end=True)
    if first is not None and last is not None and first > last:
        raise BarBuildError(f"start {start} is after end {end}")

    where = ["symbol IN (SELECT UNNEST($symbols))"]
    params: dict[str, object] = {
        "symbols": wanted,
        "pattern": str(root / "symbol=*" / "year=*" / "bars.parquet"),
    }
    if first is not None:
        # the year folder name lets DuckDB skip whole files before reading them
        where += ["open_time >= $first", "CAST(year AS BIGINT) >= $first_year"]
        params |= {"first": first, "first_year": _year_of(first)}
    if last is not None:
        where += ["open_time <= $last", "CAST(year AS BIGINT) <= $last_year"]
        params |= {"last": last, "last_year": _year_of(last)}

    columns = ", ".join(["symbol", *BAR_COLUMNS])
    query = f"""
        SELECT {columns}
        FROM read_parquet($pattern, hive_partitioning = true)
        WHERE {" AND ".join(where)}
        ORDER BY open_time, symbol
    """
    with duckdb.connect() as connection:
        frame = connection.execute(query, params).df()

    if frame.empty and start is None and end is None:
        raise BarBuildError(f"no bars found for {sorted(wanted)} ({interval}) under {out_dir}")
    return frame


def available_symbols(interval: str, out_dir: Path = DEFAULT_OUT_DIR) -> list[str]:
    """Coins that have bars for this interval."""
    root = out_dir / "source=binance" / f"interval={interval}"
    return sorted(p.name.removeprefix("symbol=") for p in root.glob("symbol=*") if p.is_dir())


def first_open_time(symbol: str, interval: str, out_dir: Path = DEFAULT_OUT_DIR) -> int | None:
    """Timestamp of the earliest bar held for one coin, or None when there are none.

    Only the timestamp column is read, so this stays fast even over the whole history.
    """
    interval_us(interval)
    pattern = str(
        out_dir
        / "source=binance"
        / f"interval={interval}"
        / f"symbol={symbol}"
        / "year=*"
        / "bars.parquet"
    )
    with duckdb.connect() as connection:
        try:
            value = connection.execute(
                "SELECT min(open_time) FROM read_parquet($pattern)", {"pattern": pattern}
            ).fetchone()
        except duckdb.IOException:  # no files match the pattern
            return None
    return None if value is None or value[0] is None else int(value[0])
