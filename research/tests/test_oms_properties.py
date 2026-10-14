"""Generated numeric(38,18) lifecycles, not invented market observations (135)."""

from decimal import Decimal, localcontext

import pytest
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, precondition, rule
from test_loss_risk import guard
from test_oms import Risk, auth

from helios.common.types import ExecutionReport, Fill, Mode, OrderState
from helios.sim.oms import OMSError, OrderManagementSystem


def amount(units):
    with localcontext() as context:
        context.prec = 80
        return Decimal(units) * Decimal("1e-18")


class ConservationMachine(RuleBasedStateMachine):
    @initialize(units=st.integers(min_value=1, max_value=10**38 - 1))
    def start(self, units):
        self.total, self.filled = units, 0
        self.clock, self.sequence = 10, 0
        self.oms = OrderManagementSystem(
            "property", Mode.BACKTEST, Risk(), id_factory=lambda: "one"
        )
        self.authorised = auth(quantity=amount(units))
        self.order = self.oms.submit(self.authorised)
        self.reports = []
        self.oms.mark_pending(self.order.order_id, self.clock)
        self.deliver(OrderState.ACCEPTED)

    def current(self):
        return self.oms.get(self.order.order_id)

    def deliver(self, state, delta=0):
        self.clock += 1
        event = None
        if delta:
            event = Fill(
                fill_id=f"fill-{self.sequence}",
                order_id=self.order.order_id,
                symbol=self.order.request.symbol,
                side=self.order.request.side,
                quantity=amount(delta),
                price=Decimal(100),
                fee=Decimal(0),
                fee_asset="USDT",
                timestamp=self.clock,
                venue_id="property_fixture",
                liquidity="TAKER",
                mode=Mode.BACKTEST,
            )
        report = ExecutionReport(
            order_id=self.order.order_id,
            client_order_id=self.order.request.client_order_id,
            sequence=self.sequence,
            timestamp=self.clock,
            state=state,
            filled_quantity=amount(self.filled),
            remaining_quantity=amount(self.total - self.filled),
            fill=event,
        )
        self.oms.on_report(report)
        self.sequence += 1
        self.reports.append(report)

    @precondition(
        lambda self: (
            self.current().state
            in (OrderState.ACCEPTED, OrderState.PARTIALLY_FILLED, OrderState.PENDING_CANCEL)
        )
    )
    @rule(units=st.integers(min_value=1, max_value=10**38 - 1))
    def partial_or_full_fill(self, units):
        remaining = self.total - self.filled
        delta = 1 + (units - 1) % remaining
        self.filled += delta
        self.deliver(
            OrderState.FILLED if self.filled == self.total else OrderState.PARTIALLY_FILLED, delta
        )

    @precondition(
        lambda self: self.current().state in (OrderState.ACCEPTED, OrderState.PARTIALLY_FILLED)
    )
    @rule()
    def cancel_request(self):
        self.clock += 1
        self.oms.request_cancel(self.order.order_id, self.clock)

    @precondition(
        lambda self: (
            self.current().state
            in (OrderState.ACCEPTED, OrderState.PARTIALLY_FILLED, OrderState.PENDING_CANCEL)
        )
    )
    @rule(expire=st.booleans())
    def cancel_or_expire(self, expire):
        state = (
            OrderState.EXPIRED
            if expire and self.current().state is not OrderState.PENDING_CANCEL
            else OrderState.CANCELLED
        )
        self.deliver(state)

    @rule(index=st.integers(min_value=0, max_value=1000))
    def duplicate_report_never_rewinds_or_adds_fill(self, index):
        old = self.current()
        assert self.oms.on_report(self.reports[index % len(self.reports)]) == old

    @rule()
    def client_retry_returns_current_original(self):
        assert self.oms.submit(self.authorised) == self.current()
        assert len(self.oms.snapshot()) == 1

    @rule()
    def illegal_report_cannot_mutate_state(self):
        old = self.current()
        report = ExecutionReport(
            order_id=old.order_id,
            client_order_id=old.request.client_order_id,
            sequence=self.sequence,
            timestamp=self.clock + 1,
            state=OrderState.CREATED,
            filled_quantity=old.filled_quantity,
            remaining_quantity=old.remaining_quantity,
        )
        with pytest.raises(OMSError):
            self.oms.on_report(report)
        assert self.current() == old

    @invariant()
    def quantities_conserved_and_never_negative(self):
        order = self.current()
        with localcontext() as context:
            context.prec = 80
            assert order.filled_quantity + order.remaining_quantity == order.request.quantity
        assert order.filled_quantity == amount(self.filled)
        assert order.remaining_quantity >= 0
        if order.state is OrderState.FILLED:
            assert order.remaining_quantity == 0


TestOMSConservation = ConservationMachine.TestCase
TestOMSConservation.settings = settings(
    max_examples=200, stateful_step_count=40, deadline=None, derandomize=True
)


def test_old_authorization_cannot_create_after_daily_guard_trip():
    risk = guard()
    oms = OrderManagementSystem("kill_property", Mode.BACKTEST, risk)
    from test_common_types import request

    first = risk.check(request()).authorised
    future = risk.check(request(client_order_id="future")).authorised
    original = oms.submit(first)
    risk.trip(10, "test_operator")
    with pytest.raises(OMSError, match="risk"):
        oms.submit(future)
    assert oms.submit(first) == original and oms.snapshot() == (original,)
