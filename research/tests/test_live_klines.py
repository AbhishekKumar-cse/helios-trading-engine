import asyncio
import json
from copy import deepcopy
from decimal import Decimal

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from helios.data import live_klines as live

OPEN_MS = 1_800_000_000_000  # synthetic aligned fixture, never a market observation
END_US = (OPEN_MS + 60_000) * 1000


def message(closed=True):
    return {
        "e": "kline",
        "E": OPEN_MS + 60_001,
        "s": "BTCUSDT",
        "k": {
            "s": "BTCUSDT",
            "i": "1m",
            "x": closed,
            "t": OPEN_MS,
            "T": OPEN_MS + 59_999,
            "o": "100.00",
            "h": "103.00",
            "l": "99.00",
            "c": "102.25",
            "v": "10",
            "q": "1000",
            "V": "4",
            "Q": "400",
            "n": 12,
        },
    }


@pytest.mark.parametrize("combined", [False, True])
def test_only_closed_public_kline_is_decoded_without_losing_decimal_or_time(combined):
    payload = message()
    raw = {"stream": "btcusdt@kline_1m", "data": payload} if combined else payload
    bar = live.decode_closed_kline(json.dumps(raw), ("BTCUSDT",), received_time=END_US + 9000)
    assert bar.close == Decimal("102.25")
    assert bar.open_time == OPEN_MS * 1000
    assert bar.recorded_close_time + 1000 == END_US
    assert bar.event_time == END_US + 1000
    assert bar.received_time == END_US + 9000
    assert (
        live.decode_closed_kline(
            json.dumps(message(False)), ("BTCUSDT",), received_time=END_US + 9000
        )
        is None
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"x": "true"},
        {"s": "ETHUSDT"},
        {"i": "1h"},
        {"t": OPEN_MS + 1},
        {"t": True},
        {"T": OPEN_MS + 59_998},
        {"o": "NaN"},
        {"c": 102.25},
        {"h": "101"},
        {"V": "11"},
        {"n": True},
    ],
)
def test_malformed_or_mismatched_observations_never_become_bars(changes):
    raw = message()
    raw["k"].update(changes)
    with pytest.raises(live.KlineStreamError):
        live.decode_closed_kline(json.dumps(raw), ("BTCUSDT",), received_time=END_US + 9000)


def test_unavailable_close_foreign_envelope_and_shutdown_fail_closed():
    raw = message()
    with pytest.raises(live.KlineStreamError):
        live.decode_closed_kline(json.dumps(raw), ("BTCUSDT",), received_time=END_US - 1)
    raw["E"] = OPEN_MS + 59_999
    with pytest.raises(live.KlineStreamError):
        live.decode_closed_kline(json.dumps(raw), ("BTCUSDT",), received_time=END_US + 9000)
    for raw in (
        {"stream": "ethusdt@kline_1m", "data": message()},
        {"e": "serverShutdown", "E": OPEN_MS},
        {"code": 2, "msg": "error"},
        [],
    ):
        with pytest.raises(live.KlineStreamError):
            live.decode_closed_kline(json.dumps(raw), ("BTCUSDT",), received_time=END_US + 9000)
    with pytest.raises(live.KlineStreamError):
        live.decode_closed_kline("invalid json", ("BTCUSDT",), received_time=END_US + 9000)


@pytest.mark.parametrize("seconds", [0, -1, True, float("nan"), float("inf"), 3601])
def test_invalid_observation_duration_rejected_before_connection(seconds, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid config must not connect")

    monkeypatch.setattr(live, "connect", forbidden)
    with pytest.raises(live.KlineStreamError):
        asyncio.run(live.observe_closed_klines(("BTCUSDT",), seconds, lambda _: None))


def test_url_uses_only_public_read_only_kline_paths():
    assert live.stream_url(("BTCUSDT", "ETHUSDT")) == (
        "wss://data-stream.binance.vision/stream?streams=btcusdt@kline_1m/ethusdt@kline_1m"
    )
    for symbols, endpoint in (
        ((), "data"),
        (("BTCUSDT", "BTCUSDT"), "data"),
        (("btcusdt",), "data"),
        (("BTCUSDT?token=private",), "data"),
        (("BTCUSDT",), "https://unknown.example"),
    ):
        with pytest.raises(live.KlineStreamError):
            live.stream_url(symbols, endpoint)


def test_real_loopback_transport_filters_updates_and_respects_deadline(monkeypatch):
    async def run():
        raw = message()
        # Actual current client clock must follow this synthetic fixture's close.
        raw["k"]["t"] = 0
        raw["k"]["T"] = 59_999
        raw["E"] = 60_001

        async def handler(websocket):
            interim = deepcopy(raw)
            interim["k"]["x"] = False
            await websocket.send(json.dumps(interim))
            await websocket.send(json.dumps(raw))
            await websocket.wait_closed()

        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]

            def loopback(uri, **kwargs):
                assert uri == live.stream_url(("BTCUSDT",))
                assert "additional_headers" not in kwargs
                return connect(f"ws://127.0.0.1:{port}", **kwargs)

            monkeypatch.setattr(live, "connect", loopback)
            bars = []
            summary = await live.observe_closed_klines(("BTCUSDT",), 0.1, bars.append)
            assert len(bars) == 1
            assert summary.received_updates == 2 and summary.closed_bars == {"BTCUSDT": 1}
            assert 0.1 <= summary.connected_seconds < 2

    asyncio.run(run())


def test_transport_disconnect_is_visible_and_never_reported_as_completion(monkeypatch):
    async def run():
        async def handler(websocket):
            await websocket.close()

        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            monkeypatch.setattr(
                live, "connect", lambda uri, **kw: connect(f"ws://127.0.0.1:{port}", **kw)
            )
            with pytest.raises(ConnectionClosed):
                await live.observe_closed_klines(("BTCUSDT",), 10, lambda _: None)

    asyncio.run(run())
