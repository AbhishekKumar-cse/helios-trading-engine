"""Build Parquet bars from the downloaded Binance zips (steps 051-052).

    uv run python scripts/build_bars.py --symbol universe --interval 1h
    uv run python scripts/build_bars.py --symbol BTCUSDT --interval 1m

Reads every monthly zip, puts timestamps in one unit, checks the rows, drops duplicate
timestamps, and writes one Parquet file per year, plus a validation and a gap report under
data/processed/reports/. Nothing is repaired or filled in: bad rows and gaps are only
recorded.
"""

import argparse
import sys
from pathlib import Path

from helios.data.bars import (
    DEFAULT_OUT_DIR,
    DEFAULT_REPORT_DIR,
    BarBuildError,
    build_bars,
    write_reports,
)
from helios.data.binance import DEFAULT_DATA_DIR, resolve_symbols
from helios.data.klines import INTERVAL_US


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", action="append", required=True, help="or 'universe'")
    parser.add_argument("--interval", required=True, choices=sorted(INTERVAL_US))
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    args = parser.parse_args(argv)

    failures = 0
    for symbol in resolve_symbols(args.symbol):
        try:
            result = build_bars(symbol, args.interval, args.data_dir, args.out_dir)
        except BarBuildError as exc:
            print(f"error: {exc}", file=sys.stderr)
            failures += 1
            continue
        reports = write_reports(result, args.report_dir)
        print(
            f"{symbol} {args.interval}: {result.rows:,} bars from {result.months_read} months "
            f"-> {len(result.files_written)} parquet files | "
            f"bad rows {len(result.bad_rows)} | duplicates dropped {result.duplicates_dropped} "
            f"| off-grid {len(result.off_grid)} | missing {result.missing_bars:,} "
            f"| reports {len(reports)}",
            flush=True,
        )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
