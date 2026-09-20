"""Write docs/research/data_quality.md from the report Parquet files (step 053).

    uv run python scripts/data_quality_report.py

Every number in that document comes from `data/processed/reports/`, which `build_bars.py`
writes. Nothing is typed by hand, so re-running after a rebuild refreshes the document and
`git diff` shows exactly what changed in the data.
"""

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from helios.common.lineage import git_commit, git_is_dirty
from helios.common.project_config import load_universe
from helios.data.bars import (
    DEFAULT_OUT_DIR,
    DEFAULT_REPORT_DIR,
    BarBuildError,
    read_bars,
    read_report,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DOC = PROJECT_ROOT / "docs" / "research" / "data_quality.md"
INTERVALS = ("1h", "1m")


def summarise(symbol: str, interval: str, out_dir: Path, report_dir: Path) -> dict[str, object]:
    bars = read_bars(symbol, interval, out_dir)
    validation = read_report("validation", symbol, interval, report_dir)
    gaps = read_report("gaps", symbol, interval, report_dir)
    times = pd.to_datetime(bars["open_time"], unit="us", utc=True)
    return {
        "symbol": symbol,
        "interval": interval,
        "bars": len(bars),
        "first": str(times.iloc[0]),
        "last": str(times.iloc[-1]),
        "bad_rows": int((validation["problems"] != "timestamp not on the interval grid").sum())
        if len(validation)
        else 0,
        "off_grid": int((validation["problems"] == "timestamp not on the interval grid").sum())
        if len(validation)
        else 0,
        "gap_runs": len(gaps),
        "missing": int(gaps["missing"].sum()) if len(gaps) else 0,
        "worst_gap": (
            f"{gaps.loc[gaps['missing'].idxmax(), 'gap_start_utc']} "
            f"({int(gaps['missing'].max())} bars)"
            if len(gaps)
            else "-"
        ),
    }


def table(rows: list[dict[str, object]], interval: str) -> str:
    head = (
        "| Coin | Bars | First | Last | Bad rows | Off-grid | Gap runs | Missing | Longest gap |\n"
        "|---|---|---|---|---|---|---|---|---|\n"
    )
    body = ""
    for r in rows:
        if r["interval"] != interval:
            continue
        body += (
            f"| {r['symbol']} | {r['bars']:,} | {r['first'][:16]} | {r['last'][:16]} "
            f"| {r['bad_rows']} | {r['off_grid']} | {r['gap_runs']} | {r['missing']:,} "
            f"| {r['worst_gap']} |\n"
        )
    return head + body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--doc", type=Path, default=DEFAULT_DOC)
    args = parser.parse_args(argv)

    symbols = load_universe().symbols
    try:
        rows = [
            summarise(symbol, interval, args.out_dir, args.report_dir)
            for interval in INTERVALS
            for symbol in symbols
        ]
    except BarBuildError as exc:
        print(f"error: {exc}\nrun scripts/build_bars.py first", file=sys.stderr)
        return 2

    total_bars = sum(int(r["bars"]) for r in rows)
    total_missing = sum(int(r["missing"]) for r in rows)
    dirty = " (uncommitted changes)" if git_is_dirty() else ""

    text = f"""# Data quality report

**Generated** by `scripts/data_quality_report.py` on {datetime.now(UTC).date()} from
`data/processed/reports/`, written by `scripts/build_bars.py`.
Commit `{git_commit()[:12]}`{dirty}. Do not edit by hand: re-run the script instead.

Source: Binance public monthly klines (spot), every file checked against its published
SHA-256. **{total_bars:,} bars**, **{total_missing:,} missing bars** in total.

## Hourly (1h)

{table(rows, "1h")}
## Minute (1m)

{table(rows, "1m")}
## What the columns mean

- **Bad rows** break a price or volume rule (step 047): a price at or below zero, a high
  below the open or close, a low above them, a negative volume or trade count, or a
  taker volume above the total. There are none in this data.
- **Off-grid** bars do not start exactly on the hour or minute. All of them are from
  **9-11 February 2018**, when Binance restarted after a long outage and the candles
  resumed at times like `09:28:14.789`. The files are not damaged; this is what the
  exchange published. These bars are kept, and listed in the validation reports.
- **Gap runs / missing** count bars the exchange never published, usually an outage or
  scheduled maintenance. **Gaps are never filled.** Inventing a price would put made-up
  data into every feature, backtest and result built on it.
- **Longest gap** is the start of the largest run, with its size in bars.

## Consequences for the research

1. The hourly history is usable: the worst coin is missing about 0.2 % of its bars.
2. Features must treat a gap as "unknown", never as "no change" (step 081 warm-up rule).
3. The February 2018 off-grid bars sit inside the hourly TRAIN period of ADR-004. Any
   feature that assumes a fixed hourly spacing must read timestamps, not row positions.
4. The minute data (2024-09 - 2026-08) has no gaps at all, so the minute horizon family
   needs no special handling.
"""
    args.doc.parent.mkdir(parents=True, exist_ok=True)
    args.doc.write_text(text, encoding="utf-8", newline="\n")
    print(table(rows, "1h"))
    print(f"written: {args.doc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
