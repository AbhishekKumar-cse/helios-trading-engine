"""Public equity observation service; no broker order API.

OBSERVE is useful for uptime measurement while no candidate is eligible. Its
heartbeats never count as PAPER fills or a promoted-alpha seven-day trial.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import signal
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from helios.data.equities import sha256, write_json
from helios.equities.calendar import normal_sessions
from helios.equities.public_data import parse_candles

IST = ZoneInfo("Asia/Kolkata")


class Continuity:
    """Detect a paused host/process without counting suspended time as uptime."""

    def __init__(self, poll_seconds: float) -> None:
        self.limit = max(30.0, 3 * poll_seconds)
        self.previous: tuple[float, float] | None = None
        self.gaps = 0
        self.max_gap = 0.0

    def check(self, monotonic: float, wall: float) -> bool:
        gap = (
            0.0
            if self.previous is None
            else max(monotonic - self.previous[0], wall - self.previous[1])
        )
        self.previous = monotonic, wall
        self.max_gap = max(self.max_gap, gap)
        if gap > self.limit:
            self.gaps += 1
            return False
        return True


def session_is_open(now: datetime, calendar: Path) -> bool:
    local = now.astimezone(IST)
    day = local.date()
    return bool(normal_sessions(calendar, day, day)) and 555 <= local.hour * 60 + local.minute < 930


def public_get(url: str) -> bytes:
    allowed = (
        "https://api.upstox.com/v3/historical-candle/intraday/",
        "https://query1.finance.yahoo.com/v8/finance/chart/",
    )
    if not url.startswith(allowed):
        raise ValueError("service permits public read-only data endpoints only")
    request = urllib.request.Request(url, headers={"User-Agent": "HELIOS academic observer"})
    with urllib.request.urlopen(request, timeout=15) as response:
        body: bytes = response.read()
        return body


def observe_service(
    root: Path,
    run_id: str,
    calendar: Path,
    *,
    symbol: str = "RELIANCE",
    isin: str = "INE002A01018",
    seconds: float = 86400,
    poll_seconds: float = 10,
) -> Path:
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", run_id) or not re.fullmatch(r"[A-Z0-9&-]+", symbol):
        raise ValueError("invalid equity observation scope")
    if seconds <= 0 or not 2 <= poll_seconds <= 60 or not re.fullmatch(r"IN[A-Z0-9]{10}", isin):
        raise ValueError("invalid observation duration/interval/instrument")
    destination = root / run_id
    destination.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    start_wall = datetime.now(UTC).isoformat()
    identity = dict(
        version="nse_public_observer_v1",
        mode="OBSERVE",
        is_simulated=True,
        run_id=run_id,
        symbol=symbol,
        isin=isin,
        started_at=start_wall,
        requested_seconds=seconds,
        poll_seconds=poll_seconds,
        calendar_sha256=sha256(calendar),
        source_sha256=sha256(Path(__file__)),
        paper_orders_enabled=False,
        purpose="operational public-data collection only",
    )
    write_json(destination / "session.json", identity)
    stopping = False

    def stop(signum: int, frame: Any) -> None:
        nonlocal stopping
        stopping = True

    previous = {name: signal.signal(name, stop) for name in (signal.SIGINT, signal.SIGTERM)}
    event_count, polls, candles, failures = 0, 0, 0, 0
    last_open: int | None = None
    status = "STARTING"
    continuity = Continuity(poll_seconds)
    error: BaseException | None = None
    with (destination / "events.jsonl").open("x") as journal:

        def event(kind: str, **fields: Any) -> None:
            nonlocal event_count
            journal.write(
                json.dumps(
                    dict(
                        event=kind,
                        received_time=time.time_ns() // 1000,
                        elapsed_seconds=time.monotonic() - started,
                        **fields,
                    )
                )
                + "\n"
            )
            journal.flush()
            event_count += 1

        try:
            while not stopping and time.monotonic() - started < seconds:
                now = datetime.now(UTC)
                if not continuity.check(time.monotonic(), now.timestamp()):
                    event("HEARTBEAT_GAP", max_gap_seconds=continuity.max_gap)
                if not session_is_open(now, calendar):
                    status = "IDLE_MARKET_CLOSED"
                    event("HEARTBEAT", status=status)
                else:
                    url = (
                        "https://api.upstox.com/v3/historical-candle/intraday/"
                        + urllib.parse.quote("NSE_EQ|" + isin, safe="")
                        + "/minutes/1"
                    )
                    try:
                        raw = public_get(url)
                        received = time.time_ns() // 1000
                        event(
                            "RAW_CANDLES", body=raw.decode(), sha256=hashlib.sha256(raw).hexdigest()
                        )
                        polls += 1
                        day = now.astimezone(IST).date()
                        frame, excluded = parse_candles(raw, symbol, day, day)
                        if not frame.empty:
                            closed = frame.loc[frame.open_time + 60_000_000 <= received]
                            if not closed.empty:
                                latest = closed.iloc[-1]
                                opening = int(latest.open_time)
                                if last_open is None or opening > last_open:
                                    if last_open is not None and opening != last_open + 60_000_000:
                                        event("GAP", previous=last_open, current=opening)
                                    event(
                                        "OBSERVED_CLOSED_MINUTE",
                                        open_time=opening,
                                        close=float(latest.close),
                                        source_exclusions=excluded,
                                        scheduled_close_time=opening + 60_000_000,
                                        received_delay_us=received - opening - 60_000_000,
                                    )
                                    last_open = opening
                                    candles += 1
                        status = "OBSERVING"
                    except Exception as data_error:
                        failures += 1
                        status = "DATA_UNAVAILABLE"
                        event("DATA_ERROR", error_type=type(data_error).__name__)
                        if isinstance(data_error, urllib.error.HTTPError) and data_error.code in (
                            401,
                            403,
                        ):
                            stopping = True
                            event("ACCESS_REQUIRED", status=data_error.code)
                        # No access workarounds or manufactured quote observations.
                heartbeat = dict(
                    status=status,
                    mode="OBSERVE",
                    is_simulated=True,
                    started_at=start_wall,
                    updated_at=datetime.now(UTC).isoformat(),
                    elapsed_seconds=time.monotonic() - started,
                    polls=polls,
                    observed_closed_candles=candles,
                    failures=failures,
                    paper_fills=0,
                    paper_orders_enabled=False,
                    continuity_gaps=continuity.gaps,
                )
                temporary = destination / "heartbeat.tmp"
                temporary.write_text(json.dumps(heartbeat) + "\n")
                temporary.replace(destination / "heartbeat.json")
                time.sleep(min(poll_seconds, max(0, seconds - (time.monotonic() - started))))
            event("SERVICE_STOP", requested_stop=stopping)
        except BaseException as exc:
            error = exc
            event("SERVICE_FAILED", error_type=type(exc).__name__)
        finally:
            for name, handler in previous.items():
                signal.signal(name, handler)
    elapsed = time.monotonic() - started
    continuity.check(time.monotonic(), time.time())
    write_json(
        destination / "artifact.json",
        dict(
            **identity,
            elapsed_seconds=elapsed,
            uptime_24h_observed=elapsed >= 86400
            and not continuity.gaps
            and error is None
            and not stopping,
            continuity_gaps=continuity.gaps,
            maximum_heartbeat_gap_seconds=continuity.max_gap,
            error_type=type(error).__name__ if error else None,
            status="FAILED" if error else "STOPPED" if stopping else "FINISHED",
            events=event_count,
            polls=polls,
            observed_closed_candles=candles,
            failures=failures,
            session_sha256=sha256(destination / "session.json"),
            events_sha256=sha256(destination / "events.jsonl"),
            seven_day_paper_trial_complete=False,
            observed_paper_fills=0,
        ),
    )
    if error is not None:
        raise error
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--calendar", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path("reports_out/equity_observer"))
    parser.add_argument("--symbol", default="RELIANCE")
    parser.add_argument("--isin", default="INE002A01018")
    parser.add_argument("--seconds", type=float, default=86400)
    parser.add_argument("--poll-seconds", type=float, default=10)
    args = parser.parse_args()
    print(
        observe_service(
            args.root,
            args.run_id,
            args.calendar,
            symbol=args.symbol,
            isin=args.isin,
            seconds=args.seconds,
            poll_seconds=args.poll_seconds,
        )
    )


if __name__ == "__main__":
    main()
