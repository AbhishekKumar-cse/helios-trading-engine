"""Public read-only one-minute Binance kline observation (154).

This first client stops on disconnect or malformed data. Reconnection and gap
recovery are step 159; no strategy, orders, database or historical store is wired.
"""

import asyncio
import json
import re
import time
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Literal, Self

from pydantic import Field, StrictInt, model_validator
from websockets.asyncio.client import connect

from helios.common.types import NonNegative, Price, Record, Timestamp

ENDPOINTS = {
    "data": "wss://data-stream.binance.vision",
    "spot443": "wss://stream.binance.com:443",
    "spot9443": "wss://stream.binance.com:9443",
}


class KlineStreamError(ValueError):
    pass


class ClosedKline(Record):
    source: Literal["binance_public_kline_1m"] = "binance_public_kline_1m"
    symbol: str = Field(pattern=r"^[A-Z0-9]+USDT$")
    interval: Literal["1m"] = "1m"
    open_time: Timestamp
    recorded_close_time: Timestamp
    event_time: Timestamp
    received_time: Timestamp
    open: Price
    high: Price
    low: Price
    close: Price
    volume: NonNegative
    quote_volume: NonNegative
    trades: StrictInt = Field(ge=0)
    taker_buy_base: NonNegative
    taker_buy_quote: NonNegative

    @model_validator(mode="after")
    def _complete(self) -> Self:
        end = self.recorded_close_time + 1000  # inclusive exchange milliseconds
        if (
            self.open_time % 60_000_000
            or end - self.open_time != 60_000_000
            or min(self.event_time, self.received_time) < end
        ):
            raise ValueError("closed minute requires aligned complete bounds and availability")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("OHLC lies outside recorded low/high")
        if self.low > self.high:
            raise ValueError("low exceeds high")
        if self.taker_buy_base > self.volume or self.taker_buy_quote > self.quote_volume:
            raise ValueError("taker volume exceeds total volume")
        return self


def stream_url(symbols: tuple[str, ...], endpoint: str = "data") -> str:
    if (
        not symbols
        or len(symbols) > 5
        or len(set(symbols)) != len(symbols)
        or any(not re.fullmatch(r"[A-Z0-9]+USDT", s) for s in symbols)
        or endpoint not in ENDPOINTS
    ):
        raise KlineStreamError("select one to five unique uppercase USDT symbols/public endpoint")
    streams = "/".join(f"{s.lower()}@kline_1m" for s in symbols)
    return f"{ENDPOINTS[endpoint]}/stream?streams={streams}"


def decode_closed_kline(
    message: str | bytes, symbols: tuple[str, ...], *, received_time: int
) -> ClosedKline | None:
    """Ignore only genuine in-progress updates; refuse malformed/foreign data."""
    try:
        envelope = json.loads(message)
        if not isinstance(envelope, dict):
            raise KlineStreamError("expected a kline object")
        payload = envelope.get("data", envelope)
        if not isinstance(payload, dict) or payload.get("e") != "kline":
            raise KlineStreamError("unexpected event, error or server shutdown")
        kline = payload["k"]
        if (
            not isinstance(kline, dict)
            or payload.get("s") not in symbols
            or kline.get("s") != payload["s"]
            or kline.get("i") != "1m"
            or type(kline.get("x")) is not bool
            or ("stream" in envelope and envelope["stream"] != f"{payload['s'].lower()}@kline_1m")
        ):
            raise KlineStreamError("stream symbol/interval/closed flag mismatch")
        if not kline["x"]:
            return None

        def micros(value: object) -> int:
            if type(value) is not int or value < 0:
                raise KlineStreamError("exchange times must be integer milliseconds")
            return value * 1000

        def number(key: str) -> Decimal:
            value = kline[key]
            if not isinstance(value, str):
                raise KlineStreamError("exchange decimal values must be strings")
            return Decimal(value)

        return ClosedKline(
            symbol=payload["s"],
            open_time=micros(kline["t"]),
            recorded_close_time=micros(kline["T"]),
            event_time=micros(payload["E"]),
            received_time=received_time,
            trades=kline["n"],
            **{
                name: number(key)
                for name, key in (
                    ("open", "o"),
                    ("high", "h"),
                    ("low", "l"),
                    ("close", "c"),
                    ("volume", "v"),
                    ("quote_volume", "q"),
                    ("taker_buy_base", "V"),
                    ("taker_buy_quote", "Q"),
                )
            },
        )
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise KlineStreamError("malformed or unexpected closed-kline observation") from exc


class StreamSummary(Record):
    started_time: Timestamp
    finished_time: Timestamp
    connected_seconds: float = Field(ge=0, allow_inf_nan=False)
    received_updates: int = Field(ge=0)
    closed_bars: dict[str, int]


async def observe_closed_klines(
    symbols: tuple[str, ...],
    seconds: float,
    emit: Callable[[ClosedKline], None],
    *,
    endpoint: str = "data",
) -> StreamSummary:
    """One bounded connection; library answers server pings with matching pongs."""
    url = stream_url(symbols, endpoint)
    if isinstance(seconds, bool) or not isfinite(seconds) or not 0 < seconds <= 3600:
        raise KlineStreamError("observation duration must be finite, positive and <=3600 seconds")
    async with connect(
        url,
        open_timeout=15,
        close_timeout=5,
        ping_interval=None,
        max_size=65_536,
        max_queue=16,
    ) as websocket:
        started = time.time_ns() // 1000
        beginning = time.monotonic()
        deadline = beginning + seconds
        updates = 0
        counts = dict.fromkeys(symbols, 0)
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                message = await asyncio.wait_for(websocket.recv(), timeout=min(15, remaining))
            except TimeoutError as exc:
                if time.monotonic() >= deadline:
                    break
                raise KlineStreamError("public stream stalled for 15 seconds") from exc
            updates += 1
            bar = decode_closed_kline(message, symbols, received_time=time.time_ns() // 1000)
            if bar is not None:
                emit(bar)
                counts[bar.symbol] += 1
        return StreamSummary(
            started_time=started,
            finished_time=time.time_ns() // 1000,
            connected_seconds=time.monotonic() - beginning,
            received_updates=updates,
            closed_bars=counts,
        )
