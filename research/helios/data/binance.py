"""Binance public-data downloads: monthly spot kline zips (steps 039-041).

Binance publishes free monthly files at https://data.binance.vision:

    https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1h/BTCUSDT-1h-2026-08.zip
    (+ the same URL ending in .CHECKSUM, a SHA-256 of the zip)

Files are saved in the layout already used in `data/`:

    data/binance/spot/klines_1h/BTCUSDT-1h-2026-08.zip

Step 039 (this file so far): build the list of monthly URLs and target paths, and show them
with `--dry-run`. Step 040 adds the download with retries; step 041 checks the checksums.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

BASE_URL = "https://data.binance.vision/data/spot/monthly/klines"
# research/helios/data/binance.py -> parents[3] is the project root
DEFAULT_DATA_DIR = Path(__file__).resolve().parents[3] / "data"

# Kline intervals Binance publishes as monthly files
INTERVALS = (
    "1s", "1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d",
)  # fmt: skip

_MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
_SYMBOL = re.compile(r"^[A-Z0-9]{5,20}$")


class BinanceDownloadError(Exception):
    """Raised for invalid download requests (bad symbol, interval or month range)."""


@dataclass(frozen=True, order=True)
class Month:
    """A calendar month such as 2026-08."""

    year: int
    month: int

    @classmethod
    def parse(cls, text: str) -> Month:
        m = _MONTH.match(text)
        if not m:
            raise BinanceDownloadError(f"month must look like YYYY-MM, got {text!r}")
        return cls(int(m.group(1)), int(m.group(2)))

    def next(self) -> Month:
        return Month(self.year + 1, 1) if self.month == 12 else Month(self.year, self.month + 1)

    def __str__(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"


def month_range(start: Month, end: Month) -> list[Month]:
    """All months from `start` to `end`, both included."""
    if start > end:
        raise BinanceDownloadError(f"start {start} is after end {end}")
    months = [start]
    while months[-1] < end:
        months.append(months[-1].next())
    return months


@dataclass(frozen=True)
class KlineFile:
    """One monthly kline file: where to download it from and where to save it."""

    symbol: str
    interval: str
    month: Month
    data_dir: Path = DEFAULT_DATA_DIR

    @property
    def filename(self) -> str:
        return f"{self.symbol}-{self.interval}-{self.month}.zip"

    @property
    def url(self) -> str:
        return f"{BASE_URL}/{self.symbol}/{self.interval}/{self.filename}"

    @property
    def checksum_url(self) -> str:
        return f"{self.url}.CHECKSUM"

    @property
    def path(self) -> Path:
        return self.data_dir / "binance" / "spot" / f"klines_{self.interval}" / self.filename


def plan_klines(
    symbols: Sequence[str],
    interval: str,
    start: Month,
    end: Month,
    data_dir: Path = DEFAULT_DATA_DIR,
) -> list[KlineFile]:
    """Every monthly file needed for `symbols` x months, in symbol then month order."""
    if interval not in INTERVALS:
        raise BinanceDownloadError(f"interval must be one of {INTERVALS}, got {interval!r}")
    if not symbols:
        raise BinanceDownloadError("give at least one symbol")
    for s in symbols:
        if not _SYMBOL.match(s):
            raise BinanceDownloadError(f"symbol must be upper-case letters/digits, got {s!r}")
    months = month_range(start, end)
    return [KlineFile(s, interval, m, data_dir) for s in symbols for m in months]


# ---------------------------------------------------------------- command line


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="download_binance",
        description="Download Binance monthly spot kline zips into data/binance/spot/.",
    )
    p.add_argument(
        "--symbol",
        action="append",
        required=True,
        help="e.g. BTCUSDT; repeat for several, or 'universe' for all coins in configs/",
    )
    p.add_argument("--interval", required=True, choices=INTERVALS)
    p.add_argument("--start", required=True, help="first month, YYYY-MM")
    p.add_argument("--end", required=True, help="last month, YYYY-MM")
    p.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    p.add_argument("--dry-run", action="store_true", help="only print URLs and target paths")
    return p


def resolve_symbols(values: Sequence[str]) -> list[str]:
    """Expand 'universe' into the coins from configs/universe.yaml."""
    symbols: list[str] = []
    for v in values:
        if v.lower() == "universe":
            from helios.common.project_config import load_universe

            symbols.extend(load_universe().symbols)
        else:
            symbols.append(v)
    return list(dict.fromkeys(symbols))  # keep order, drop duplicates


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        files = plan_klines(
            resolve_symbols(args.symbol),
            args.interval,
            Month.parse(args.start),
            Month.parse(args.end),
            args.data_dir,
        )
    except BinanceDownloadError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not args.dry_run:
        print("error: downloading is added in step 040; use --dry-run for now", file=sys.stderr)
        return 2

    for f in files:
        state = "exists " if f.path.is_file() else "missing"
        print(f"{state}  {f.url}  ->  {f.path}")
    present = sum(f.path.is_file() for f in files)
    print(
        f"{len(files)} files planned: {present} already on disk, {len(files) - present} to download"
    )
    return 0
