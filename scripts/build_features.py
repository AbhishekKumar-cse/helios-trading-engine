"""Export all coins' features and availability masks from canonical Parquet bars.

    uv run python scripts/build_features.py --interval 1h
    uv run python scripts/build_features.py --interval 1m --symbol BTCUSDT

Default symbols come from configs/universe.yaml. Off-grid rows are retained as
unavailable and counted. Warm-up, gaps and invalid feature outputs stay NaN.
"""

import argparse
import sys
from pathlib import Path

from helios.common.config import ConfigError
from helios.common.lineage import LineageError
from helios.data.bars import DEFAULT_OUT_DIR as BARS_DIR
from helios.data.bars import BarBuildError
from helios.data.binance import resolve_symbols
from helios.data.klines import INTERVAL_US
from helios.features.registry import FeatureError
from helios.features.store import DEFAULT_FEATURE_DIR, build_features


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", required=True, choices=sorted(INTERVAL_US))
    parser.add_argument(
        "--symbol", action="append", help="repeat for multiple coins; default: universe"
    )
    parser.add_argument("--bars-dir", type=Path, default=BARS_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_FEATURE_DIR)
    args = parser.parse_args(argv)
    try:
        symbols = resolve_symbols(args.symbol or ["universe"])
    except (ConfigError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    failures = 0
    for symbol in symbols:
        try:
            result = build_features(symbol, args.interval, args.bars_dir, args.out_dir)
        except (BarBuildError, FeatureError, LineageError, OSError, ValueError) as exc:
            print(f"error: {symbol} {args.interval}: {exc}", file=sys.stderr)
            failures += 1
            continue
        print(
            f"{symbol} {args.interval}: {result.rows:,} rows -> "
            f"{len(result.files_written)} parquet "
            f"files | off-grid rows retained unavailable: {result.off_grid_rows:,} "
            f"| manifest {result.manifest}",
            flush=True,
        )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
