"""Download Binance monthly spot klines (steps 039-044).

Run from the project root in Ubuntu, for example:

    uv run python scripts/download_binance.py --symbol BTCUSDT --interval 1h \
        --start 2026-06 --end 2026-08 --dry-run

    uv run python scripts/download_binance.py --symbol universe --interval 1m \
        --start 2024-09 --end 2026-08 --dry-run

The logic lives in helios.data.binance (tested); this file is only the entry point.
"""

import sys

from helios.data.binance import main

if __name__ == "__main__":
    sys.exit(main())
