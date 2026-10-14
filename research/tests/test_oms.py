from concurrent.futures import ThreadPoolExecutor

import pytest
from test_common_types import request

from helios.common.types import AuthorisedOrder, Mode, OrderState, ReasonCode, RiskDecision
from helios.sim.oms import OMSError, OrderManagementSystem


class Risk:
    def __init__(self):
        self.calls = 0
        self.halted = False

    def check(self, action):
        self.calls += 1
        if self.halted:
            return RiskDecision(
                accepted=False, reason=ReasonCode.HALTED, timestamp=action.timestamp
            )
        return RiskDecision(
            accepted=True,
            reason=ReasonCode.ACCEPTED,
            timestamp=action.timestamp,
            authorised=AuthorisedOrder(action=action, limits_hash="b" * 64),
        )


def auth(**changes):
    return AuthorisedOrder(action=request(**changes), limits_hash="b" * 64)


def test_duplicate_submission_returns_original_and_concurrent_retry_creates_once():
    risk = Risk()
    oms = OrderManagementSystem("fixture", Mode.BACKTEST, risk)
    with ThreadPoolExecutor(max_workers=8) as pool:
        orders = list(pool.map(lambda _: oms.submit(auth()), range(20)))
    assert len({o.order_id for o in orders}) == 1 and risk.calls == 1
    assert len(oms.snapshot()) == 1 and orders[0].state is OrderState.CREATED
    assert (
        orders[0].filled_quantity == 0
        and orders[0].remaining_quantity == orders[0].request.quantity
    )


def test_client_id_payload_conflict_and_mode_mismatch_refused():
    oms = OrderManagementSystem("fixture", Mode.BACKTEST, Risk())
    original = oms.submit(auth())
    with pytest.raises(OMSError, match="different"):
        oms.submit(auth(symbol="ETHUSDT"))
    with pytest.raises(OMSError, match="mode"):
        oms.submit(auth(client_order_id="other", mode=Mode.PAPER))
    assert oms.snapshot() == (original,)


def test_stale_authorization_cannot_create_after_kill_trip():
    risk = Risk()
    oms = OrderManagementSystem("fixture", Mode.BACKTEST, risk)
    prior = oms.submit(auth())
    risk.halted = True
    assert oms.submit(auth()) == prior  # lookup only; no resubmission
    with pytest.raises(OMSError, match="risk"):
        oms.submit(auth(client_order_id="new"))
    assert len(oms.snapshot()) == 1


def test_id_collision_refused_and_normal_ids_are_unique_across_sessions():
    oms = OrderManagementSystem("fixture", Mode.BACKTEST, Risk(), id_factory=lambda: "same")
    oms.submit(auth())
    with pytest.raises(OMSError, match="collision"):
        oms.submit(auth(client_order_id="second"))
    first = OrderManagementSystem("fixture", Mode.BACKTEST, Risk()).submit(auth())
    second = OrderManagementSystem("fixture", Mode.BACKTEST, Risk()).submit(auth())
    assert first.order_id != second.order_id
