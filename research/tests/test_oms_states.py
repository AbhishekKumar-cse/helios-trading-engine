from decimal import Decimal as D

import pytest
from test_oms import Risk, auth

from helios.common.types import ExecutionReport, Fill, Mode, OrderState, ReasonCode
from helios.sim.oms import OMSError, OrderManagementSystem


def book():
    oms = OrderManagementSystem("states", Mode.BACKTEST, Risk())
    order = oms.submit(auth(quantity=D(3)))
    oms.mark_pending(order.order_id, 10)
    return oms, order


def report(order, seq, state, filled="0", fill=None, **changes):
    return ExecutionReport(
        **(
            dict(
                order_id=order.order_id,
                client_order_id=order.request.client_order_id,
                sequence=seq,
                timestamp=11 + seq,
                state=state,
                filled_quantity=D(filled),
                remaining_quantity=D(3) - D(filled),
                fill=fill,
            )
            | changes
        )
    )


def fill(order, qty, identity="fill", timestamp=12):
    return Fill(
        fill_id=identity,
        order_id=order.order_id,
        symbol=order.request.symbol,
        side=order.request.side,
        quantity=D(qty),
        price=D(100),
        fee=D(".01"),
        fee_asset="USDT",
        timestamp=timestamp,
        venue_id="fixture",
        liquidity="TAKER",
        mode=Mode.BACKTEST,
    )


def test_lifecycle_ack_partial_full_and_duplicate_delivery():
    oms, order = book()
    ack = report(order, 0, OrderState.ACCEPTED)
    accepted = oms.on_report(ack)
    assert accepted.filled_quantity == 0
    partial = report(order, 1, OrderState.PARTIALLY_FILLED, "1", fill(order, 1))
    changed = oms.on_report(partial)
    assert changed.filled_quantity == 1 and changed.remaining_quantity == 2
    assert oms.on_report(ack) == changed  # late identical retry doesn't rewind
    final = report(order, 2, OrderState.FILLED, "3", fill(order, 2, "final", 13))
    closed = oms.on_report(final)
    assert closed.remaining_quantity == 0 and oms.on_report(final) == closed
    assert oms.submit(auth(quantity=D(3))) == closed


def test_cancel_fill_race_preserves_unfilled_residual():
    oms, order = book()
    oms.on_report(report(order, 0, OrderState.ACCEPTED))
    oms.request_cancel(order.order_id, 11)
    oms.on_report(report(order, 1, OrderState.PARTIALLY_FILLED, "1", fill(order, 1)))
    cancelled = oms.on_report(report(order, 2, OrderState.CANCELLED, "1"))
    assert cancelled.filled_quantity == 1 and cancelled.remaining_quantity == 2
    with pytest.raises(OMSError, match="illegal"):
        oms.on_report(report(order, 3, OrderState.ACCEPTED, "1"))


def test_rejection_does_not_fabricate_fill():
    oms, order = book()
    rejected = oms.on_report(
        report(order, 0, OrderState.REJECTED, reason=ReasonCode.VENUE_REJECTED)
    )
    assert rejected.filled_quantity == 0 and rejected.remaining_quantity == 3
    with pytest.raises(OMSError):
        oms.mark_pending(order.order_id, 12)


@pytest.mark.parametrize(
    "problem", ["missing_sequence", "conflict", "no_fill", "overfill", "backwards", "client"]
)
def test_bad_report_is_atomic_and_book_stays_unchanged(problem):
    oms, order = book()
    ack = report(order, 0, OrderState.ACCEPTED)
    current = oms.on_report(ack)
    bad = report(order, 1, OrderState.PARTIALLY_FILLED, "1", fill(order, 1))
    if problem == "missing_sequence":
        bad = bad.model_copy(update={"sequence": 2})
    if problem == "conflict":
        bad = ack.model_copy(update={"timestamp": 12})
    if problem == "no_fill":
        bad = bad.model_copy(update={"fill": None})
    if problem == "overfill":
        bad = bad.model_copy(update={"filled_quantity": D(4), "remaining_quantity": D(0)})
    if problem == "backwards":
        bad = bad.model_copy(update={"timestamp": 10})
    if problem == "client":
        bad = bad.model_copy(update={"client_order_id": "unknown"})
    with pytest.raises(ValueError):
        oms.on_report(bad)
    assert oms.get(order.order_id) == current


def test_fill_before_ack_and_reused_fill_id_refused():
    oms, order = book()
    with pytest.raises(OMSError):
        oms.on_report(report(order, 0, OrderState.PARTIALLY_FILLED, "1", fill(order, 1)))
    oms.on_report(report(order, 0, OrderState.ACCEPTED))
    current = oms.on_report(report(order, 1, OrderState.PARTIALLY_FILLED, "1", fill(order, 1)))
    with pytest.raises(OMSError):
        oms.on_report(
            report(order, 2, OrderState.PARTIALLY_FILLED, "2", fill(order, 1, timestamp=13))
        )
    assert oms.get(order.order_id) == current
