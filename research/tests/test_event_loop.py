from decimal import Decimal as D
from types import SimpleNamespace

import pytest
from test_common_types import request

from helios.common.types import Bar, Mode, OrderType
from helios.sim.event_loop import BarEventLoop

H = 3_600_000_000


def bars():
    return [
        Bar(
            symbol="BTCUSDT",
            source="fixture",
            sequence=i,
            open_time=i * H,
            ingest_time=(i + 1) * H,
            interval="1h",
            open=D(100 + i),
            high=D(110 + i),
            low=D(90 + i),
            close=D(105 + i),
            volume=D(1),
            snapshot_id="snapshot",
        )
        for i in range(3)
    ]


def test_next_open_only_and_tail_intents_remain_unexecuted():
    events = bars()
    calls = []

    def decide(bar):
        calls.append(("decision", bar.close_time))
        return [
            request(
                client_order_id=str(bar.sequence),
                timestamp=bar.close_time,
                mode=Mode.REPLAY,
                order_type=OrderType.MARKET,
                price=None,
            )
        ]

    def act(action, opening):
        calls.append(("act", opening.timestamp))
        assert opening.price == D(100 + opening.timestamp // H)
        assert not hasattr(opening, "close") and not hasattr(opening, "high")
        assert action.timestamp <= opening.timestamp

    tail = BarEventLoop().run(SimpleNamespace(events=lambda: iter(events)), decide, act)
    assert calls == [
        ("decision", H),
        ("act", H),
        ("decision", 2 * H),
        ("act", 2 * H),
        ("decision", 3 * H),
    ]
    assert len(tail) == 1 and tail[0].decision_open_time == 2 * H


def test_delayed_ingest_cannot_execute_at_a_past_open():
    events = bars()
    events[0] = events[0].model_copy(update={"ingest_time": H + 1})
    acted = []

    def decide(bar):
        return [request(timestamp=bar.ingest_time)] if bar.sequence == 0 else []

    BarEventLoop().run(
        SimpleNamespace(events=lambda: iter(events)),
        decide,
        lambda action, opening: acted.append(opening.timestamp),
    )
    assert acted == [2 * H]


@pytest.mark.parametrize("kind", ["gap", "partial", "snapshot", "order"])
def test_bad_source_fails_before_callbacks(kind):
    events = bars()
    if kind == "gap":
        events.pop(1)
    if kind == "partial":
        events[0] = events[0].model_copy(update={"recorded_close_time": H // 2})
    if kind == "snapshot":
        events[0] = events[0].model_copy(update={"snapshot_id": "other"})
    if kind == "order":
        events.reverse()
    with pytest.raises(ValueError):
        BarEventLoop().run(
            SimpleNamespace(events=lambda: iter(events)),
            lambda bar: pytest.fail("source accepted"),
            lambda *args: None,
        )


def test_future_or_duplicate_intents_refused():
    source = SimpleNamespace(events=lambda: iter(bars()))
    with pytest.raises(ValueError, match="intent"):
        BarEventLoop().run(
            source, lambda bar: [request(timestamp=bar.close_time + 1)], lambda *args: None
        )
    with pytest.raises(ValueError, match="intent"):
        BarEventLoop().run(
            source, lambda bar: [request(timestamp=bar.close_time)] * 2, lambda *args: None
        )
