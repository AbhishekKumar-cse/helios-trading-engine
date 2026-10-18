"""Bounded public-data NSE PAPER integration run, never a promoted-alpha trial.

Requires clean source, a registered minute formula and a source-verified NSE
instrument row. Public observations that are late, missing or stale halt the
same risk/OMS/venue/ledger used by the crypto runner; timestamps are not shifted.
"""

import argparse
import json
import time
import urllib.parse
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import Engine, text

from helios.common.db import get_engine
from helios.common.lineage import PROJECT_ROOT, RunContext, git_commit, git_is_dirty
from helios.data.equities import sha256, write_json
from helios.equities.live import EquityClosedCandle
from helios.equities.paper_config import equity_paper_config
from helios.equities.public_data import parse_candles
from helios.equities.service import IST, public_get, session_is_open
from helios.paper.runtime import PaperRuntime, PaperSafetyStop
from helios.paper.store import PaperStore
from helios.sim.evaluate import _definition as registered_definition
from helios.sim.loss_risk import PostgresTripStore


def run_equity_paper(
    run_id: str,
    calendar: Path,
    *,
    seconds: float = 180,
    symbol: str = "RELIANCE",
    isin: str = "INE002A01018",
    alpha_id: str = "nse_minute_round1_momentum",
    root: Path = Path("reports_out/equity_paper"),
    snapshot: Path = PROJECT_ROOT / "data/equities/nifty50_minutes/20261017_public_round1",
    engine: Engine | None = None,
) -> Path:
    if git_is_dirty():
        raise ValueError("reported NSE PAPER execution requires clean source")
    equity_paper_config(run_id, "0" * 64, alpha_id, symbol)
    manifest = json.loads((snapshot / "manifest.json").read_text())
    matches = [row for row in manifest["files"] if row["symbol"] == symbol]
    if len(matches) != 1 or matches[0]["isin"] != isin:
        raise ValueError("PAPER symbol/ISIN must match the frozen public data roster")
    if seconds <= 0 or not session_is_open(datetime.now(UTC), calendar):
        raise ValueError("NSE PAPER smoke requires an open normal session and positive duration")
    engine = get_engine() if engine is None else engine
    with engine.connect() as connection:
        definition = registered_definition(connection, alpha_id, 1)
        row = (
            connection.execute(
                text(
                    "SELECT venue,quote_asset,lot_size,tick_size FROM instruments WHERE symbol=:s"
                ),
                dict(s=symbol),
            )
            .mappings()
            .one()
        )
        if row["venue"] != "nse_cash" or row["quote_asset"] != "INR" or row["lot_size"] != 1:
            raise ValueError("registered NSE cash instrument metadata required")
    destination = root / run_id
    destination.mkdir(parents=True, exist_ok=False)
    identity = destination / "session.json"
    write_json(
        identity,
        dict(
            version="nse_paper_session_v1",
            run_id=run_id,
            mode="PAPER",
            is_simulated=True,
            purpose="integration_only_rejected_candidate",
            started_time=time.time_ns() // 1000,
            symbol=symbol,
            isin=isin,
            seconds=seconds,
            code_commit=git_commit(),
            calendar_sha256=sha256(calendar),
            instrument_tick_size=str(row["tick_size"]),
            source="public Upstox closed minutes and Yahoo timestamped last trade",
        ),
    )
    config = equity_paper_config(run_id, sha256(identity), alpha_id, symbol)
    context = RunContext.capture(config, config.stream_id, 0, reported=True)
    store = PaperStore(engine, config, context)
    runtime = PaperRuntime(config, definition, context.code_commit, PostgresTripStore(engine))
    log_path = destination / "observations.jsonl"
    error: BaseException | None = None
    started = time.monotonic()
    with log_path.open("x") as log:

        def record(kind: str, **fields: object) -> None:
            log.write(json.dumps(dict(event=kind, **fields), default=str) + "\n")
            log.flush()

        try:
            while time.monotonic() - started < seconds:
                now = datetime.now(UTC)
                if not session_is_open(now, calendar):
                    break
                url = (
                    "https://api.upstox.com/v3/historical-candle/intraday/"
                    + urllib.parse.quote("NSE_EQ|" + isin, safe="")
                    + "/minutes/1"
                )
                raw = public_get(url)
                received = time.time_ns() // 1000
                record("RAW_CANDLES", received_time=received, body=raw.decode())
                day = now.astimezone(IST).date()
                frame, _ = parse_candles(raw, symbol, day, day)
                closed = frame.loc[frame.open_time + 60_000_000 <= received]
                if not closed.empty:
                    latest = closed.iloc[-1]
                    opening = int(latest.open_time)
                    if not runtime.bars or opening > runtime.bars[-1].open_time:
                        runtime.closed(
                            EquityClosedCandle(
                                symbol=symbol,
                                open_time=opening,
                                recorded_close_time=opening + 60_000_000 - 1,
                                event_time=opening + 60_000_000,
                                received_time=received,
                                open=Decimal(str(latest.open)),
                                high=Decimal(str(latest.high)),
                                low=Decimal(str(latest.low)),
                                close=Decimal(str(latest.close)),
                                volume=Decimal(str(latest.volume)),
                            )
                        )
                if runtime.bars:
                    quote_url = (
                        "https://query1.finance.yahoo.com/v8/finance/chart/"
                        + urllib.parse.quote(symbol + ".NS", safe="")
                        + "?interval=1m&range=1d"
                    )
                    quote = public_get(quote_url)
                    received = time.time_ns() // 1000
                    record("RAW_QUOTE", received_time=received, body=quote.decode())
                    runtime.message(quote, received)
                store.save(runtime)
                time.sleep(min(2, max(0, seconds - (time.monotonic() - started))))
        except BaseException as exc:
            error = exc
        finally:
            try:
                runtime.halt("equity_session_end", max(runtime.clock, time.time_ns() // 1000))
                store.save(runtime)
            except BaseException as exc:
                error = error or exc
            record(
                "SESSION_END",
                status="FAILED" if error else "FINISHED",
                error_type=type(error).__name__ if error else None,
            )
    artifact = destination / "artifact.json"
    write_json(
        artifact,
        dict(
            version="nse_paper_artifact_v1",
            mode="PAPER",
            is_simulated=True,
            purpose=config.purpose,
            status="FAILED" if error else "FINISHED",
            error_type=type(error).__name__ if error else None,
            error_reason=str(error) if isinstance(error, PaperSafetyStop) else None,
            config=config.model_dump(mode="json"),
            experiment_id=store.experiment_id,
            context=asdict(context),
            elapsed_seconds=time.monotonic() - started,
            stream_identity_sha256=sha256(identity),
            observations_sha256=sha256(log_path),
            bars=[b.model_dump(mode="json") for b in runtime.bars],
            trace=runtime.trace().model_dump(mode="json"),
            limitations=[
                "No promotion, TEST or real order routing.",
                "Public last trade is a proxy, not an executable quote.",
                "No automatic restart reconciliation or seven-day trial claim.",
                "15+5 bps per side is an unverified research cost scenario.",
            ],
        ),
    )
    store.finish(artifact, sha256(artifact), failed=error is not None)
    if error is not None:
        raise error
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--calendar", required=True, type=Path)
    parser.add_argument("--seconds", type=float, default=180)
    args = parser.parse_args()
    print(run_equity_paper(args.run_id, args.calendar, seconds=args.seconds))


if __name__ == "__main__":
    main()
