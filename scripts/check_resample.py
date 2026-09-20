"""Cross-check: minute bars resampled to hours vs the hourly files Binance published (step 055).

    uv run python scripts/check_resample.py                    # every coin in the universe
    uv run python scripts/check_resample.py --symbol BTCUSDT

The two sets come from different downloads, so agreement is real evidence that the
downloads, the millisecond/microsecond handling and the Parquet build are all correct.
Prints the number of hours compared and the number that disagree; exits 1 if any do.
"""

import argparse
import sys
from pathlib import Path

from helios.common.project_config import load_universe
from helios.data.bars import DEFAULT_OUT_DIR
from helios.data.loader import load_bars
from helios.data.resample import COMPARE_COLUMNS, compare_bars, compared_count, resample_bars


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", action="append", help="default: every coin in the universe")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--show", type=int, default=5, help="mismatch rows to print")
    args = parser.parse_args(argv)

    symbols = args.symbol or load_universe().symbols
    total_mismatches = 0

    for symbol in symbols:
        minutes = load_bars(symbol, "1m", out_dir=args.out_dir)
        first, last = minutes["open_time"].min(), minutes["open_time"].max()
        published = load_bars(symbol, "1h", first, last, out_dir=args.out_dir)

        rebuilt = resample_bars(minutes, "1m", "1h")
        hours = compared_count(rebuilt, published)
        problems = compare_bars(rebuilt, published, COMPARE_COLUMNS)
        total_mismatches += len(problems)

        print(
            f"{symbol}: {len(minutes):,} minute bars -> {len(rebuilt):,} complete hours | "
            f"compared {hours:,} hours | mismatching values {len(problems)}",
            flush=True,
        )
        if len(problems):
            print(problems.head(args.show).to_string(index=False))
            worst = problems.reindex(problems["difference"].abs().sort_values().index).tail(1)
            print("largest difference:")
            print(worst.to_string(index=False))

    print("cross-check passed" if not total_mismatches else "cross-check FAILED")
    return 1 if total_mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
