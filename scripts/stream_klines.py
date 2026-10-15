"""Observe public closed 1m bars for ten minutes; no keys, accounts or order execution."""

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path

from websockets.exceptions import WebSocketException

from helios.common.lineage import git_commit, git_is_dirty
from helios.data.binance import resolve_symbols, sha256_file
from helios.data.live_klines import (
    ENDPOINTS,
    KlineStreamError,
    observe_closed_klines,
    stream_url,
)
from helios.data.resilient_klines import observe_resilient_klines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--symbol", action="append", help="repeat; default is the five-coin universe"
    )
    parser.add_argument("--seconds", type=float, default=600)
    parser.add_argument("--endpoint", choices=sorted(ENDPOINTS), default="data")
    parser.add_argument(
        "--reconnect", action="store_true", help="retry transport failures; log gaps"
    )
    args = parser.parse_args()
    symbols = tuple(resolve_symbols(args.symbol or ["universe"]))
    try:
        url = stream_url(symbols, args.endpoint)
        module = Path(__file__).resolve().parents[1] / "research/helios/data/live_klines.py"
        print(
            json.dumps(
                dict(
                    event="SESSION_START",
                    mode="PAPER",
                    execution_enabled=False,
                    market_data="observed_public",
                    url=url,
                    symbols=symbols,
                    requested_seconds=args.seconds,
                    code_commit=git_commit(),
                    dirty=git_is_dirty(),
                    client_sha256=sha256_file(module),
                    cli_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    reconnect_enabled=args.reconnect,
                    reconnect_client_sha256=sha256_file(module.with_name("resilient_klines.py"))
                    if args.reconnect
                    else None,
                ),
                allow_nan=False,
            ),
            flush=True,
        )
        if args.reconnect:
            summary = asyncio.run(
                observe_resilient_klines(
                    symbols,
                    args.seconds,
                    lambda bar: print(bar.model_dump_json(), flush=True),
                    lambda event: print(json.dumps(event), flush=True),
                    endpoint=args.endpoint,
                )
            )
        else:
            summary = asyncio.run(
                observe_closed_klines(
                    symbols,
                    args.seconds,
                    lambda bar: print(bar.model_dump_json(), flush=True),
                    endpoint=args.endpoint,
                )
            )
        print(json.dumps(dict(event="SESSION_END", **summary.model_dump())), flush=True)
        if not all(summary.closed_bars.values()):
            raise KlineStreamError("no closed bar observed for every requested symbol")
        return 0
    except (OSError, ValueError, WebSocketException, TimeoutError) as exc:
        print(f"stream failed: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1
    except KeyboardInterrupt:
        print("stream interrupted; bounded observation incomplete", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
