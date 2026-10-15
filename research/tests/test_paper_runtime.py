import json
from decimal import Decimal

import pytest
from pydantic import ValidationError
from test_live_klines import message
from test_loss_risk import Store

from helios.alpha.definition import AlphaDefinition
from helios.common.types import Mode, OrderState
from helios.data.live_klines import decode_closed_kline
from helios.paper.config import smoke_config
from helios.paper.runtime import PaperRuntime, PaperSafetyStop, public_price
from helios.sim.event_loop import BarOpen
from helios.sim.paper import BarPaperVenue, rounded

BASE = 1_700_000_040_000


def raw(offset, *, closed=True, close="101"):
    payload = message(closed)
    payload["k"].update(t=BASE + offset * 60_000, T=BASE + (offset + 1) * 60_000 - 1, c=close)
    payload["E"] = BASE + (offset + 1) * 60_000 + 1 if closed else BASE + offset * 60_000 + 2000
    return json.dumps(payload)


def bar(offset, close="101"):
    received = (BASE + (offset + 1) * 60_000) * 1000 + 10_000
    return decode_closed_kline(raw(offset, close=close), ("BTCUSDT",), received_time=received)


def definition(config):
    return AlphaDefinition(
        alpha_id=config.alpha_id,
        version=1,
        name="Synthetic integration policy",
        provenance="QUANT",
        feature_set_version="v1",
        horizon_family="H-MINUTE",
        horizon_periods=1,
        author="test",
        expression="-sign(log_return_1)",
    )


def runtime(scope="test_paper"):
    config = smoke_config(scope, "a" * 64)
    return PaperRuntime(config, definition(config), "a" * 40, Store())


def pending(runtime):
    runtime.closed(bar(0, "100"))
    assert not runtime.oms.snapshot()
    runtime.closed(bar(1, "101"))
    assert len(runtime.oms.snapshot()) == 1
    assert runtime.oms.snapshot()[0].state is OrderState.ACCEPTED
    assert not any(report.fill for report in runtime.reports)


def test_later_received_price_fills_shared_venue_and_reconciles_ledger():
    live = runtime()
    pending(live)
    receipt = (BASE + 120_000) * 1000 + 2_010_000
    live.message(raw(2, closed=False, close="102"), receipt)
    fill = next(report.fill for report in live.reports if report.fill is not None)
    assert fill.mode is Mode.PAPER and fill.timestamp == receipt
    assert fill.timestamp > live.oms.snapshot()[0].request.timestamp
    assert fill.price == rounded(Decimal("102") * Decimal("0.9998"))
    assert fill.fee > 0 and live.snapshots[-1].fees == fill.fee
    assert live.oms.snapshot()[0].state is OrderState.FILLED
    assert live.snapshots[-1].equity == live.snapshots[-1].cash + live.positions[
        -1
    ].quantity * Decimal("102")


@pytest.mark.leakage
def test_completed_bar_never_becomes_a_backdated_opening_fill():
    live = runtime()
    pending(live)
    live.message(raw(1), bar(1).received_time)
    assert not any(report.fill for report in live.reports)
    assert public_price(raw(1), ("BTCUSDT",), bar(1).received_time) is None
    with pytest.raises(ValueError, match="PAPER"):
        BarPaperVenue(Mode.BACKTEST).on_public_price(
            BarOpen("BTCUSDT", 1, Decimal("100"), "a" * 64)
        )


@pytest.mark.parametrize("failure", ["stale", "clock", "gap", "intent"])
def test_feed_and_intent_failures_latch_kill_and_cancel_pending(failure):
    live = runtime()
    pending(live)
    receipt = (BASE + 120_000) * 1000 + 2_010_000
    packet = raw(2, closed=False)
    if failure == "stale":
        receipt += 6_000_000
    elif failure == "clock":
        receipt = live.clock
    elif failure == "gap":
        packet = raw(4, closed=False)
    else:
        packet = json.loads(packet)
        packet["E"] += 12_000
        packet = json.dumps(packet)
        receipt += 12_000_000
    with pytest.raises(PaperSafetyStop):
        live.message(packet, receipt)
    assert live.store.is_tripped(live.config.run_id)
    assert live.oms.snapshot()[0].state is OrderState.CANCELLED
    assert not any(report.fill for report in live.reports)


def test_real_mode_and_foreign_public_packets_are_refused():
    config = smoke_config("test_paper", "a" * 64)
    with pytest.raises(ValidationError):
        type(config).model_validate(config.model_dump() | dict(mode="LIVE"))
    payload = json.loads(raw(2, closed=False))
    payload["s"] = "ETHUSDT"
    with pytest.raises(ValueError):
        public_price(json.dumps(payload), ("BTCUSDT",), (BASE + 122_010) * 1000)
