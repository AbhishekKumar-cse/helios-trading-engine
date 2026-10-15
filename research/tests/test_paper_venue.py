from decimal import Decimal as D

import pytest
from test_common_types import request
from test_oms import Risk, auth

from helios.common.interfaces import ExecutionVenue
from helios.common.types import (
    Ack,
    CancelOrder,
    Mode,
    OrderState,
    OrderType,
    Reject,
    Side,
)
from helios.sim.event_loop import BarOpen
from helios.sim.oms import OrderManagementSystem
from helios.sim.paper import BarPaperVenue


def market(**changes):
    return request(**(dict(order_type=OrderType.MARKET, price=None, timestamp=10) | changes))


def opening(time=11, **changes):
    return BarOpen(
        **(dict(symbol="BTCUSDT", timestamp=time, price=D(100), snapshot_id="snapshot") | changes)
    )


@pytest.mark.parametrize("side,price", [(Side.BUY, "100.02"), (Side.SELL, "99.98")])
def test_market_next_open_slippage_fees_and_no_fill_on_ack(side, price):
    venue = BarPaperVenue(Mode.BACKTEST)
    assert isinstance(venue, ExecutionVenue) and venue.venue_info().is_simulated is True
    reports = []
    venue.subscribe_reports(reports.append)
    venue.on_open(opening(9))
    action = market(side=side)
    ack = venue.submit(action)
    assert isinstance(ack, Ack) and not reports
    venue.dispatch_reports()
    assert reports[-1].state is OrderState.ACCEPTED and reports[-1].fill is None
    assert len(reports) == 1
    venue.on_open(opening(11))
    fill = reports[-1].fill
    assert fill.price == D(price) and fill.fee == D(price) * D("0.3") / 1000
    assert fill.timestamp == 11 and fill.liquidity == "TAKER"
    assert venue.snapshot_open_orders() == []
    assert venue.submit(action) == ack
    venue.on_open(opening(12))
    assert len(reports) == 2


def test_oms_identity_and_report_ordering_and_duplicate_dispatch():
    oms = OrderManagementSystem("paper", Mode.BACKTEST, Risk())
    order = oms.submit(auth(order_type=OrderType.MARKET, price=None))
    pending = oms.mark_pending(order.order_id, 10)
    venue = BarPaperVenue(Mode.BACKTEST)
    venue.subscribe_reports(oms.on_report)
    assert venue.submit_order(pending).order_id == order.order_id
    venue.dispatch_reports()
    assert oms.get(order.order_id).state is OrderState.ACCEPTED
    venue.on_open(opening())
    assert oms.get(order.order_id).state is OrderState.FILLED


def test_cancel_retry_conflicts_and_late_commands():
    venue = BarPaperVenue(Mode.BACKTEST)
    action = market()
    ack = venue.submit(action)
    cancel = CancelOrder(
        request_id="cancel",
        order_id=ack.order_id,
        symbol=action.symbol,
        timestamp=10,
        lineage=action.lineage,
        mode=action.mode,
    )
    assert isinstance(venue.cancel(cancel), Ack)
    assert venue.cancel(cancel) == venue.cancel(cancel)
    assert isinstance(venue.submit(market(quantity=D(1))), Reject)
    venue.on_open(opening())
    assert not venue.snapshot_open_orders()
    assert isinstance(venue.submit(market(client_order_id="late")), Reject)
    assert isinstance(venue.submit(market(mode=Mode.PAPER, client_order_id="mode")), Reject)


def test_bad_open_is_atomic():
    venue = BarPaperVenue(Mode.BACKTEST)
    venue.submit(market())
    with pytest.raises(ValueError, match="snapshot"):
        venue.on_open(opening(snapshot_id="other"))
    assert len(venue.snapshot_open_orders()) == 1
    venue.on_open(opening())
    with pytest.raises(ValueError, match="advance"):
        venue.on_open(opening())


def test_delayed_oms_handoff_cannot_backdate_acknowledgement_or_fill():
    class LaterRisk(Risk):
        def check(self, action):
            return super().check(action).model_copy(update={"timestamp": action.timestamp + 2})

    oms = OrderManagementSystem("late", Mode.BACKTEST, LaterRisk())
    created = oms.submit(auth(order_type=OrderType.MARKET, price=None))
    pending = oms.mark_pending(created.order_id, 12)
    venue = BarPaperVenue(Mode.BACKTEST)
    venue.subscribe_reports(oms.on_report)
    ack = venue.submit_order(pending)
    assert ack.timestamp == 12
    venue.dispatch_reports()
    assert oms.get(created.order_id).timestamp == 12
    with pytest.raises(ValueError, match="clock"):
        venue.on_open(opening(11))
    venue.on_open(opening(12))
    assert oms.get(created.order_id).state is OrderState.FILLED
    assert venue.submit_order(pending) == ack


def test_future_cancel_cannot_be_applied_then_rewind_to_an_earlier_open():
    venue = BarPaperVenue(Mode.BACKTEST)
    action = market()
    ack = venue.submit(action)
    cancel = CancelOrder(
        request_id="future",
        order_id=ack.order_id,
        symbol=action.symbol,
        timestamp=20,
        lineage=action.lineage,
        mode=action.mode,
    )
    assert isinstance(venue.cancel(cancel), Ack)
    with pytest.raises(ValueError, match="clock"):
        venue.on_open(opening(11))


def test_stale_commands_reject_after_completed_bar_availability():
    from test_event_loop import H, bars

    venue = BarPaperVenue(Mode.BACKTEST)
    venue.on_open(opening(H))
    venue.on_bar(bars()[1].model_copy(update={"open": D(100)}))
    assert isinstance(venue.submit(market(timestamp=H + 1)), Reject)
