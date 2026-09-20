"""Fill the `instruments` table from Binance and from the bars on disk (step 058).

    uv run python scripts/seed_instruments.py --dry-run   # show what would be written
    uv run python scripts/seed_instruments.py             # write it

Tick and lot sizes come from Binance's exchange information; the first available date comes
from the Parquet bars. Running it again is harmless: rows are matched on the symbol and
updated in place.
"""

import argparse
import sys
from pathlib import Path

from sqlalchemy import text

from helios.common.db import get_engine
from helios.common.project_config import load_universe
from helios.data.bars import DEFAULT_OUT_DIR, BarBuildError
from helios.data.instruments import InstrumentError, build_specs, seed_instruments


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", default="1h", help="which bars decide the first date")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--dry-run", action="store_true", help="print, do not write")
    args = parser.parse_args(argv)

    symbols = load_universe().symbols
    try:
        specs = build_specs(symbols, args.interval, args.out_dir)
    except (InstrumentError, BarBuildError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    header = f"{'symbol':10} {'base':6} {'quote':6} {'tick size':>14} {'lot size':>14}  first data"
    print(header)
    print("-" * len(header))
    for spec in specs:
        print(
            f"{spec.symbol:10} {spec.base_asset:6} {spec.quote_asset:6} "
            f"{spec.tick_size:>14} {spec.lot_size:>14}  {spec.first_available_date}"
            f"{'' if spec.active else '  (not trading)'}"
        )

    if args.dry_run:
        print(f"\ndry run: {len(specs)} rows would be written")
        return 0

    with get_engine().begin() as connection:
        written = seed_instruments(connection, specs)
        total = connection.execute(text("SELECT count(*) FROM instruments")).scalar_one()
    print(f"\nwrote {written} rows; instruments now holds {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
