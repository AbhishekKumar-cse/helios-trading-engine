"""Turn monthly Binance zips into tidy Parquet bars (steps 051-052).

Flow for one symbol and interval:

    zips -> read_klines -> normalise_klines (one time unit) -> validate_bars + gap checks
         -> sort, drop duplicate timestamps -> Parquet, split by year

Why Parquet: the zips must be unzipped and parsed every time (about 25 s for a year of
minute bars), while Parquet is a compressed column format that loads in a fraction of a
second and keeps the exact types.

Layout (Hive style, so DuckDB and pyarrow read the parts as columns):

    data/processed/bars/source=binance/interval=1h/symbol=BTCUSDT/year=2017/bars.parquet

Nothing is repaired here. Bad rows and gaps are collected and handed back for the reports in
step 052; the bars keep exactly what the exchange published.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from helios.data.binance import DEFAULT_DATA_DIR
from helios.data.klines import (
    find_gaps,
    find_off_grid,
    interval_us,
    normalise_klines,
    read_klines,
    to_utc,
    validate_bars,
)

DEFAULT_OUT_DIR = DEFAULT_DATA_DIR / "processed" / "bars"
BAR_COLUMNS = (
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
)


class BarBuildError(Exception):
    """Raised when bars cannot be built (no input files, or nothing valid to write)."""


@dataclass
class BuildResult:
    """What one build produced, for printing and for the reports in step 052."""

    symbol: str
    interval: str
    rows: int
    files_written: list[Path] = field(default_factory=list)
    months_read: int = 0
    duplicates_dropped: int = 0
    bad_rows: pd.DataFrame = field(default_factory=pd.DataFrame)
    gaps: pd.DataFrame = field(default_factory=pd.DataFrame)
    off_grid: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def missing_bars(self) -> int:
        return 0 if self.gaps.empty else int(self.gaps["missing"].sum())


def monthly_zips(symbol: str, interval: str, data_dir: Path = DEFAULT_DATA_DIR) -> list[Path]:
    """Every downloaded monthly zip for one symbol and interval, oldest first."""
    folder = data_dir / "binance" / "spot" / f"klines_{interval}"
    return sorted(folder.glob(f"{symbol}-{interval}-*.zip"))


def load_history(symbol: str, interval: str, data_dir: Path = DEFAULT_DATA_DIR) -> pd.DataFrame:
    """Read every month of one symbol into one table, timestamps already in microseconds."""
    files = monthly_zips(symbol, interval, data_dir)
    if not files:
        raise BarBuildError(f"no {interval} zips for {symbol} under {data_dir}")
    months = [normalise_klines(read_klines(path)) for path in files]
    return pd.concat(months, ignore_index=True)


def build_bars(
    symbol: str,
    interval: str,
    data_dir: Path = DEFAULT_DATA_DIR,
    out_dir: Path = DEFAULT_OUT_DIR,
    *,
    write: bool = True,
) -> BuildResult:
    """Build the Parquet bars for one symbol and interval, and report what was found."""
    interval_us(interval)  # rejects an unknown interval before any file is read
    frame = load_history(symbol, interval, data_dir)
    months = len(monthly_zips(symbol, interval, data_dir))

    bad_rows = validate_bars(frame)
    off_grid = find_off_grid(frame, interval)

    tidy = (
        frame.drop_duplicates(subset="open_time", keep="first")
        .sort_values("open_time")
        .reset_index(drop=True)
    )
    # gaps are measured on the part that sits on the interval grid; off-grid rows are kept in
    # the bars (they are real trades) and reported separately
    on_grid = tidy.loc[tidy["open_time"] % interval_us(interval) == 0]
    gaps = find_gaps(on_grid, interval) if not on_grid.empty else pd.DataFrame()

    result = BuildResult(
        symbol=symbol,
        interval=interval,
        rows=len(tidy),
        months_read=months,
        duplicates_dropped=len(frame) - len(tidy),
        bad_rows=bad_rows,
        gaps=gaps,
        off_grid=off_grid,
    )
    if write:
        result.files_written = write_bars(tidy, symbol, interval, out_dir)
    return result


def write_bars(
    frame: pd.DataFrame, symbol: str, interval: str, out_dir: Path = DEFAULT_OUT_DIR
) -> list[Path]:
    """Write one Parquet file per calendar year and return the paths."""
    if frame.empty:
        raise BarBuildError(f"nothing to write for {symbol} {interval}")

    years = to_utc(frame["open_time"]).dt.year
    written: list[Path] = []
    for year, part in frame.groupby(years, sort=True):
        folder = (
            out_dir
            / "source=binance"
            / f"interval={interval}"
            / f"symbol={symbol}"
            / f"year={int(year)}"
        )
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "bars.parquet"
        part[list(BAR_COLUMNS)].reset_index(drop=True).to_parquet(
            path, engine="pyarrow", compression="zstd", index=False
        )
        written.append(path)
    return written


def read_bars(
    symbol: str, interval: str, out_dir: Path = DEFAULT_OUT_DIR, year: int | None = None
) -> pd.DataFrame:
    """Read bars back from Parquet (all years, or one)."""
    folder = out_dir / "source=binance" / f"interval={interval}" / f"symbol={symbol}"
    pattern = "year=*/bars.parquet" if year is None else f"year={year}/bars.parquet"
    files = sorted(folder.glob(pattern))
    if not files:
        raise BarBuildError(f"no bars under {folder}")
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
