"""Build Parquet bars from the downloaded Binance zips (steps 051-052).

    uv run python scripts/build_bars.py --symbol universe --interval 1h
    uv run python scripts/build_bars.py --symbol BTCUSDT --interval 1m

Reads every monthly zip, puts timestamps in one unit, checks the rows, drops duplicate
timestamps, and writes one Parquet file per year, plus a validation and a gap report under
data/processed/reports/. It then records a data snapshot: the exact files, their
checksums and the row count, so later results can point at the data they used.
Nothing is repaired or filled in: bad rows and gaps are only recorded.
"""

import argparse
import sys
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from helios.common.db import get_engine
from helios.data.bars import (
    DEFAULT_OUT_DIR,
    DEFAULT_REPORT_DIR,
    BarBuildError,
    build_bars,
    write_reports,
)
from helios.data.binance import DEFAULT_DATA_DIR, resolve_symbols
from helios.data.klines import INTERVAL_US
from helios.data.snapshots import SNAPSHOT_DIR, describe_bars, register_snapshot, write_manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", action="append", required=True, help="or 'universe'")
    parser.add_argument("--interval", required=True, choices=sorted(INTERVAL_US))
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--snapshot-dir", type=Path, default=SNAPSHOT_DIR)
    parser.add_argument(
        "--no-snapshot",
        action="store_true",
        help="skip recording the data snapshot (use when the database is not running)",
    )
    args = parser.parse_args(argv)

    failures = 0
    built: list[str] = []
    for symbol in resolve_symbols(args.symbol):
        try:
            result = build_bars(symbol, args.interval, args.data_dir, args.out_dir)
        except BarBuildError as exc:
            print(f"error: {exc}", file=sys.stderr)
            failures += 1
            continue
        built.append(symbol)
        reports = write_reports(result, args.report_dir)
        print(
            f"{symbol} {args.interval}: {result.rows:,} bars from {result.months_read} months "
            f"-> {len(result.files_written)} parquet files | "
            f"bad rows {len(result.bad_rows)} | duplicates dropped {result.duplicates_dropped} "
            f"| off-grid {len(result.off_grid)} | missing {result.missing_bars:,} "
            f"| reports {len(reports)}",
            flush=True,
        )
    if built and not args.no_snapshot:
        record_snapshot(built, args.interval, args.out_dir, args.snapshot_dir)

    return 1 if failures else 0


def record_snapshot(symbols: list[str], interval: str, out_dir: Path, snapshot_dir: Path) -> None:
    """Pin down exactly which files were just built, so results can point at them.

    A database that is not running must not fail the build: the manifest is still written,
    and the row can be added later by running this script again.
    """
    snapshot = describe_bars(symbols, interval, out_dir)
    manifest = write_manifest(snapshot, snapshot_dir)
    print(
        f"snapshot {snapshot.snapshot_id[:12]}... | {snapshot.file_count} files | "
        f"{snapshot.row_count:,} rows | {snapshot.first_utc:%Y-%m-%d} -> "
        f"{snapshot.last_utc:%Y-%m-%d} | manifest {manifest.name}"
    )
    try:
        with get_engine().begin() as connection:
            stored = register_snapshot(connection, snapshot)
    except SQLAlchemyError as exc:
        print(
            f"warning: snapshot not stored in the database ({type(exc).__name__})", file=sys.stderr
        )
        return
    print("stored in data_snapshots" if stored else "already in data_snapshots")


if __name__ == "__main__":
    sys.exit(main())
