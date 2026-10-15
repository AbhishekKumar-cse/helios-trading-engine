"""Bounded public reconnect loop and per-symbol closed-bar watermarks (159)."""

import asyncio
import time
from collections.abc import Callable
from typing import Any

from pydantic import Field
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake

from helios.common.types import Record
from helios.data.live_klines import ClosedKline, KlineStreamError, decode_closed_kline, stream_url

EventSink = Callable[[dict[str, Any]], None]


class ReconnectPolicy(Record):
    initial_delay: float = Field(default=1, gt=0, le=60, allow_inf_nan=False)
    maximum_delay: float = Field(default=30, gt=0, le=60, allow_inf_nan=False)
    idle_seconds: float = Field(default=15, gt=0, le=120, allow_inf_nan=False)


class ClosedWatermarks:
    def __init__(self, events: EventSink) -> None:
        self.last: dict[str, ClosedKline] = {}
        self.events = events

    def accept(self, bar: ClosedKline) -> bool:
        old = self.last.get(bar.symbol)
        if old is not None:
            if bar.open_time <= old.open_time:
                duplicate = bar.open_time == old.open_time
                if duplicate and bar.model_dump(exclude={"received_time", "event_time"}) != (
                    old.model_dump(exclude={"received_time", "event_time"})
                ):
                    raise KlineStreamError("conflicting duplicate closed bar")
                self.events(
                    dict(
                        event="DUPLICATE" if duplicate else "OUT_OF_ORDER",
                        symbol=bar.symbol,
                        open_time=bar.open_time,
                        received_time=bar.received_time,
                    )
                )
                return False
            expected = old.open_time + 60_000_000
            if bar.open_time != expected:
                self.events(
                    dict(
                        event="GAP",
                        symbol=bar.symbol,
                        expected_open_time=expected,
                        observed_open_time=bar.open_time,
                        missing_bars=(bar.open_time - expected) // 60_000_000,
                        received_time=bar.received_time,
                    )
                )
        self.last[bar.symbol] = bar
        return True


class ResilientSummary(Record):
    started_time: int
    finished_time: int
    elapsed_seconds: float
    connections: int
    disconnects: int
    received_updates: int
    closed_bars: dict[str, int]


async def observe_resilient_klines(
    symbols: tuple[str, ...],
    seconds: float,
    emit: Callable[[ClosedKline], None],
    events: EventSink,
    *,
    endpoint: str = "data",
    policy: ReconnectPolicy | None = None,
    on_message: Callable[[str | bytes, int], None] | None = None,
) -> ResilientSummary:
    """Reconnect network failures until the deadline; parser/consumer errors propagate.

    Replayed or out-of-order closes never advance state. Gaps are logged before
    delivery, never filled. Raw-message consumers must validate their own schema.
    No persistent watermark is reused across a new session or process restart.
    """
    if isinstance(seconds, bool) or not 0 < seconds <= 86_400:
        raise KlineStreamError("duration must be finite, positive and <=86400 seconds")
    url = stream_url(symbols, endpoint)
    selected = ReconnectPolicy() if policy is None else policy
    marks = ClosedWatermarks(events)
    start, beginning = time.time_ns() // 1000, time.monotonic()
    deadline = beginning + seconds
    initial_delay = min(selected.initial_delay, selected.maximum_delay)
    delay = initial_delay
    connections = disconnects = updates = 0
    counts = dict.fromkeys(symbols, 0)
    while (remaining := deadline - time.monotonic()) > 0:
        connected_at = time.monotonic()
        consumer_active = False
        try:
            async with asyncio.timeout(remaining):
                async with connect(
                    url,
                    open_timeout=min(15, remaining),
                    close_timeout=1,
                    ping_interval=None,
                    max_size=65_536,
                    max_queue=16,
                ) as socket:
                    connections += 1
                    consumer_active = True
                    events(
                        dict(
                            event="CONNECTED",
                            connection=connections,
                            received_time=time.time_ns() // 1000,
                        )
                    )
                    consumer_active = False
                    while (left := deadline - time.monotonic()) > 0:
                        raw = await asyncio.wait_for(
                            socket.recv(), min(selected.idle_seconds, left)
                        )
                        received = time.time_ns() // 1000
                        updates += 1
                        consumer_active = True
                        bar = decode_closed_kline(raw, symbols, received_time=received)
                        if bar is not None and marks.accept(bar):
                            emit(bar)
                            counts[bar.symbol] += 1
                        if on_message is not None:
                            on_message(raw, received)
                        consumer_active = False
        except (OSError, ConnectionClosed, InvalidHandshake, TimeoutError) as exc:
            if consumer_active:
                raise
            if time.monotonic() >= deadline:
                break
            disconnects += 1
            events(
                dict(
                    event="DISCONNECTED",
                    error_type=type(exc).__name__,
                    received_time=time.time_ns() // 1000,
                    retry_delay=delay,
                )
            )
            await asyncio.sleep(min(delay, max(0, deadline - time.monotonic())))
            delay = (
                initial_delay
                if time.monotonic() - connected_at >= 60
                else min(selected.maximum_delay, delay * 2)
            )
    return ResilientSummary(
        started_time=start,
        finished_time=time.time_ns() // 1000,
        elapsed_seconds=time.monotonic() - beginning,
        connections=connections,
        disconnects=disconnects,
        received_updates=updates,
        closed_bars=counts,
    )
