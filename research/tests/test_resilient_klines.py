import asyncio
import json

import pytest
from test_live_klines import END_US, message
from websockets.asyncio.server import serve

from helios.data import resilient_klines as live
from helios.data.live_klines import KlineStreamError, decode_closed_kline


def raw(offset=0):
    payload = message()
    delta = 1_700_000_040_000 - payload["k"]["t"] + offset * 60_000
    for key in ("t", "T"):
        payload["k"][key] += delta
    payload["E"] += delta
    return json.dumps(payload)


async def fault_scenario():
    events, bars = [], []
    attempts = 0

    async def handler(socket):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            await socket.send(raw())
            await socket.close(1011, "injected transport outage")
        else:
            for offset in (0, 3, 1):
                await socket.send(raw(offset))
            await socket.wait_closed()

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        original = live.stream_url
        live.stream_url = lambda *_: f"ws://127.0.0.1:{port}"
        try:
            summary = await live.observe_resilient_klines(
                ("BTCUSDT",),
                0.35,
                bars.append,
                events.append,
                policy=live.ReconnectPolicy(initial_delay=0.01, maximum_delay=0.04, idle_seconds=1),
            )
        finally:
            live.stream_url = original
    return dict(
        summary=summary.model_dump(mode="json"),
        events=events,
        bars=[bar.model_dump(mode="json") for bar in bars],
    )


def test_real_socket_disconnect_reconnect_replay_and_gap():
    proof = asyncio.run(fault_scenario())
    assert proof["summary"]["connections"] == 2
    assert proof["summary"]["disconnects"] == 1
    assert proof["summary"]["closed_bars"] == {"BTCUSDT": 2}
    assert len(proof["bars"]) == 2
    gap = next(e for e in proof["events"] if e["event"] == "GAP")
    assert gap["missing_bars"] == 2
    assert {e["event"] for e in proof["events"]} >= {"DUPLICATE", "OUT_OF_ORDER"}


@pytest.mark.parametrize("error_type", [ValueError, OSError, TimeoutError])
def test_conflicting_duplicate_and_consumer_failure_are_not_network_retries(error_type):
    marks = live.ClosedWatermarks(lambda _: None)
    bar = decode_closed_kline(raw(), ("BTCUSDT",), received_time=END_US + 1000)
    assert marks.accept(bar)
    changed = bar.model_copy(update=dict(trades=bar.trades + 1))
    with pytest.raises(KlineStreamError, match="conflicting"):
        marks.accept(changed)

    async def fail():
        async with serve(lambda s: s.send(raw()), "127.0.0.1", 0) as server:
            from unittest.mock import patch

            port = server.sockets[0].getsockname()[1]

            def consumer(_):
                raise error_type("consumer failed closed")

            with patch.object(live, "stream_url", return_value=f"ws://127.0.0.1:{port}"):
                await live.observe_resilient_klines(("BTCUSDT",), 1, consumer, lambda _: None)

    with pytest.raises(error_type, match="consumer failed"):
        asyncio.run(fail())


def test_stalled_connections_retry_with_capped_delay(monkeypatch):
    async def scenario():
        async with serve(lambda s: s.wait_closed(), "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            monkeypatch.setattr(live, "stream_url", lambda *_: f"ws://127.0.0.1:{port}")
            events = []
            summary = await live.observe_resilient_klines(
                ("BTCUSDT",),
                0.3,
                lambda _: None,
                events.append,
                policy=live.ReconnectPolicy(
                    initial_delay=0.01, maximum_delay=0.04, idle_seconds=0.02
                ),
            )
            delays = [e["retry_delay"] for e in events if e["event"] == "DISCONNECTED"]
            assert summary.disconnects >= 2 and max(delays) <= 0.04
            assert delays == sorted(delays)

    asyncio.run(scenario())
