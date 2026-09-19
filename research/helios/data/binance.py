"""Binance public-data downloads: monthly spot kline zips (steps 039-041).

Binance publishes free monthly files at https://data.binance.vision:

    https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1h/BTCUSDT-1h-2026-08.zip
    (+ the same URL ending in .CHECKSUM, a SHA-256 of the zip)

Files are saved in the layout already used in `data/`:

    data/binance/spot/klines_1h/BTCUSDT-1h-2026-08.zip

- Step 039: build the list of monthly URLs and target paths, and show them with `--dry-run`.
- Step 040: download with retries; files already on disk are skipped; months Binance does not
  have (HTTP 404, e.g. before a coin was listed) are skipped and reported.
- Step 041: every file is checked against Binance's SHA-256 checksum (kept next to the zip as
  `<file>.zip.CHECKSUM`, so later checks work offline). Damaged files are re-downloaded,
  and files already on disk are verified too.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import time
import urllib.error
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from urllib.request import Request, urlopen

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

    @property
    def checksum_path(self) -> Path:
        """Local copy of Binance's .CHECKSUM file, kept next to the zip."""
        return self.path.with_name(self.filename + ".CHECKSUM")


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


# ---------------------------------------------------------------- downloading (step 040)

USER_AGENT = "helios-research/0.1 (academic project; +https://data.binance.vision)"
CHUNK_BYTES = 1024 * 1024


class DownloadStatus(StrEnum):
    DOWNLOADED = "downloaded"
    SKIPPED = "skipped"  # already on disk and its checksum matches
    NOT_FOUND = "not-found"  # Binance has no file for this month (HTTP 404)
    FAILED = "failed"  # still failing after all retries


class ChecksumMismatchError(Exception):
    """The downloaded file's SHA-256 differs from Binance's published checksum."""


_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


def fetch_to_file(url: str, dest: Path, timeout: float = 60.0) -> int:
    """Stream `url` into `dest` via a temporary `.part` file; return the number of bytes.

    The file only appears under its final name once the download is complete, so a dropped
    connection never leaves a half file that looks finished.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    request = Request(url, headers={"User-Agent": USER_AGENT})
    size = 0
    try:
        with urlopen(request, timeout=timeout) as response, part.open("wb") as out:
            while chunk := response.read(CHUNK_BYTES):
                out.write(chunk)
                size += len(chunk)
        part.replace(dest)
    finally:
        part.unlink(missing_ok=True)
    return size


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, ChecksumMismatchError):
        return True  # damaged in transit: download again
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code >= 500 or exc.code == 429  # server error or "too many requests"
    return isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError, OSError))


def fetch_text(url: str, timeout: float = 30.0) -> str:
    """Download a small text file (such as a .CHECKSUM) and return its content."""
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        data: bytes = response.read()
    return data.decode("ascii")


def parse_checksum(text: str, filename: str) -> str:
    """Read a Binance .CHECKSUM file: '<64 hex characters>  <filename>'."""
    parts = text.split()
    if len(parts) != 2 or parts[1] != filename or not _SHA256_HEX.match(parts[0].lower()):
        raise ChecksumMismatchError(f"unexpected .CHECKSUM content for {filename}: {text!r}")
    return parts[0].lower()


def sha256_file(path: Path) -> str:
    """SHA-256 of a file, read in chunks (works for files larger than memory)."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def expected_checksum(f: KlineFile, get_text: Callable[[str], str] = fetch_text) -> str:
    """Binance's checksum for `f`: from the local copy if present, else downloaded and saved."""
    if f.checksum_path.is_file():
        return parse_checksum(f.checksum_path.read_text(encoding="ascii"), f.filename)
    text = get_text(f.checksum_url)
    expected = parse_checksum(text, f.filename)  # validate before saving
    f.checksum_path.parent.mkdir(parents=True, exist_ok=True)
    f.checksum_path.write_text(text, encoding="ascii")
    return expected


def download_file(
    f: KlineFile,
    *,
    retries: int = 4,
    backoff_seconds: float = 2.0,
    fetch: Callable[[str, Path], int] = fetch_to_file,
    get_text: Callable[[str], str] = fetch_text,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[DownloadStatus, str]:
    """Make sure one monthly file is on disk and matches Binance's SHA-256 checksum.

    - File already on disk and checksum matches: SKIPPED.
    - File missing, or on disk but damaged: (re)download, then check the checksum.
    - A checksum mismatch after download deletes the file and counts as a failed attempt.
    - Network problems are retried with growing waits; never raises for them.
    """
    replaced = False
    for attempt in range(retries + 1):
        try:
            expected = expected_checksum(f, get_text)
            if f.path.is_file():
                if sha256_file(f.path) == expected:
                    return DownloadStatus.SKIPPED, "already on disk, checksum OK"
                f.path.unlink()
                replaced = True
            size = fetch(f.url, f.path)
            actual = sha256_file(f.path)
            if actual != expected:
                f.path.unlink()
                raise ChecksumMismatchError(
                    f"got sha256 {actual[:12]}..., expected {expected[:12]}..."
                )
            note = ", replaced a damaged file" if replaced else ""
            return DownloadStatus.DOWNLOADED, f"{size / 1e6:.1f} MB, checksum OK{note}"
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return DownloadStatus.NOT_FOUND, "Binance has no file for this month (404)"
            error: Exception = exc
        except Exception as exc:  # noqa: BLE001 - classified below
            error = exc
        if not _is_retryable(error) or attempt == retries:
            return DownloadStatus.FAILED, f"{type(error).__name__}: {error}"
        sleep(backoff_seconds * 2**attempt)
    raise AssertionError("unreachable")


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
    p.add_argument("--retries", type=int, default=4, help="extra attempts per file (default 4)")
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
        return run_downloads(files, retries=args.retries)

    for f in files:
        state = "exists " if f.path.is_file() else "missing"
        print(f"{state}  {f.url}  ->  {f.path}")
    present = sum(f.path.is_file() for f in files)
    print(
        f"{len(files)} files planned: {present} already on disk, {len(files) - present} to download"
    )
    return 0


def run_downloads(files: Sequence[KlineFile], *, retries: int = 4) -> int:
    """Download every file in order, print one line each and a summary. Exit code 1 if any
    file FAILED (so scripts and CI notice), otherwise 0."""
    counts = dict.fromkeys(DownloadStatus, 0)
    for n, f in enumerate(files, start=1):
        status, message = download_file(f, retries=retries)
        counts[status] += 1
        print(f"[{n}/{len(files)}] {status:<10} {f.filename}  ({message})", flush=True)
    summary = ", ".join(f"{counts[s]} {s}" for s in DownloadStatus)
    print(f"done: {summary}")
    return 1 if counts[DownloadStatus.FAILED] else 0
