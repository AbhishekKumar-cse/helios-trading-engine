from decimal import Decimal as D

import pytest
from test_common_types import request

from helios.common.interfaces import RiskEngine
from helios.common.types import ReasonCode, RiskState
from helios.sim.risk import CheckChain, RiskCheck


def state(**changes):
    return RiskState(
        **(dict(timestamp=10, halted=False, daily_pnl=D(0), limits_hash="b" * 64) | changes)
    )


def test_first_failure_stops_chain_without_authorization():
    seen = []

    def first(action, snapshot):
        seen.append("first")
        return None

    def fail(action, snapshot):
        seen.append("fail")
        return ReasonCode.POSITION_LIMIT

    def later(action, snapshot):
        pytest.fail("must short-circuit")

    engine: RiskEngine = CheckChain(
        (RiskCheck("first", first), RiskCheck("limit", fail), RiskCheck("later", later)), state
    )
    result = engine.check(request())
    assert seen == ["first", "fail"]
    assert not result.accepted and result.reason is ReasonCode.POSITION_LIMIT
    assert result.authorised is None


def test_accept_carries_exact_action_and_applied_limit_hash():
    action = request()
    result = CheckChain((RiskCheck("fixture", lambda *args: None),), state).check(action)
    assert result.accepted and result.authorised.action == action
    assert result.authorised.limits_hash == "b" * 64


@pytest.mark.parametrize("failure", ["check", "provider", "wrong_return", "accepted_code"])
def test_exceptions_and_invalid_check_results_fail_closed(failure):
    def explode(*args):
        raise RuntimeError("private state")

    check = explode if failure == "check" else lambda *args: None
    provider = explode if failure == "provider" else state
    if failure == "wrong_return":

        def check(*args):
            return False

    if failure == "accepted_code":

        def check(*args):
            return ReasonCode.ACCEPTED

    decision = CheckChain((RiskCheck("check", check),), provider).check(request())
    assert decision.reason is ReasonCode.INTERNAL_ERROR and decision.authorised is None
    assert "private state" not in decision.model_dump_json()


@pytest.mark.parametrize(
    "changes,reason",
    [
        (dict(halted=True), ReasonCode.HALTED),
        (dict(limits_hash=None), ReasonCode.MISSING_LIMITS),
        (dict(timestamp=9), ReasonCode.STALE_MARKET_DATA),
    ],
)
def test_mandatory_state_guards_precede_checks(changes, reason):
    def forbidden(*args):
        pytest.fail("guard must short-circuit")

    decision = CheckChain((RiskCheck("never", forbidden),), lambda: state(**changes)).check(
        request()
    )
    assert decision.reason is reason and not decision.accepted


def test_empty_chain_cannot_approve_and_duplicate_names_refused():
    assert CheckChain((), state).check(request()).reason is ReasonCode.MISSING_LIMITS
    check = RiskCheck("same", lambda *args: None)
    with pytest.raises(ValueError):
        CheckChain((check, check), state)
