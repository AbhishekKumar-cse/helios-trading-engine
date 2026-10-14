from decimal import Decimal as D

import pytest
from sqlalchemy import text
from test_common_types import lineage, request
from test_portfolio_risk import risk
from test_schema_trading import trading as _trading_fixture

from helios.common.types import CancelOrder, Mode, ReasonCode
from helios.sim.loss_risk import DailyRisk, DailyRiskLimits, RiskTrip, record_trip, tripped

trading = pytest.fixture(_trading_fixture.__wrapped__)


class Store:
    def __init__(self):
        self.events = []

    def is_tripped(self, scope):
        return any(e.scope == scope for e in self.events)

    def trip(self, event):
        if not self.is_tripped(event.scope):
            self.events.append(event)


def guard(pnl="0", store=None):
    base = risk(current="0", orders=())
    config = DailyRiskLimits(
        **(base.config.model_dump() | dict(scope="fixture", daily_loss_limit=D(100)))
    )
    active = DailyRisk(
        config,
        lambda: base.state().model_copy(
            update={"daily_pnl": D(pnl), "limits_hash": active.limits_hash}
        ),
        base.prices,
        base.portfolio,
        Store() if store is None else store,
    )
    return active


def test_daily_boundary_latches_and_zero_new_orders_after_trip():
    good = guard("-99.99")
    assert good.check(request()).accepted
    active = guard("-100")
    assert active.check(request()).reason is ReasonCode.DAILY_LOSS_LIMIT
    assert len(active.store.events) == 1
    active.state = good.state
    for _ in range(4):
        assert active.check(request()).reason is ReasonCode.HALTED
    restarted = guard(store=active.store)
    assert restarted.check(request()).reason is ReasonCode.HALTED


def test_manual_trip_independent_of_provider_and_cancel_cleanup():
    active = guard()
    active.trip(10, "operator")
    assert active.check(request()).reason is ReasonCode.HALTED
    cancel = CancelOrder(
        request_id="cancel",
        order_id="order",
        symbol="BTCUSDT",
        timestamp=10,
        lineage=lineage(),
        mode=Mode.BACKTEST,
    )
    assert active.check(cancel).accepted


def test_journal_failure_is_not_authorization_and_local_flag_remains():
    active = guard("-100")

    def fail(event):
        raise RuntimeError("journal unavailable")

    active.store.trip = fail
    assert active.check(request()).reason is ReasonCode.INTERNAL_ERROR
    assert active.check(request()).reason is ReasonCode.HALTED


def test_actual_risk_event_insert_is_idempotent_and_scope_latched(trading):
    digest = "e" * 64
    trading.execute(
        text(
            "INSERT INTO risk_limits(limit_set_id,scope,version,limits,author,effective_from,hash) "
            "VALUES ('t_daily_limits','t_daily_scope',1,'{}','fixture',now(),:hash)"
        ),
        {"hash": digest},
    )
    event = RiskTrip(
        scope="t_daily_scope",
        timestamp=10,
        reason=ReasonCode.DAILY_LOSS_LIMIT,
        limits_hash=digest,
        actor="test",
    )
    assert not tripped(trading, event.scope)
    record_trip(trading, event)
    record_trip(trading, event)
    assert tripped(trading, event.scope)
    assert (
        trading.execute(
            text("SELECT count(*) FROM risk_events WHERE subject_ref='t_daily_scope' ")
        ).scalar_one()
        == 1
    )
