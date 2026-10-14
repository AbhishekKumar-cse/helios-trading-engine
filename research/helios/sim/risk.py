"""Synchronous ordered risk framework; explicit reject on any internal error (124)."""

from collections.abc import Callable
from dataclasses import dataclass

from helios.common.types import (
    AuthorisedOrder,
    CancelOrder,
    OrderAction,
    ReasonCode,
    RiskDecision,
    RiskState,
)


@dataclass(frozen=True)
class RiskCheck:
    name: str
    check: Callable[[OrderAction, RiskState], ReasonCode | None]


class CheckChain:
    def __init__(self, checks: tuple[RiskCheck, ...], state: Callable[[], RiskState]) -> None:
        if any(not c.name.strip() for c in checks) or len({c.name for c in checks}) != len(checks):
            raise ValueError("risk checks require distinct nonempty names")
        self.checks, self.state = tuple(checks), state

    def check(self, action: OrderAction) -> RiskDecision:
        clock = action.timestamp
        try:
            state = RiskState.model_validate(self.state().model_dump())
            clock = state.timestamp
            if clock < action.timestamp:
                reason = ReasonCode.STALE_MARKET_DATA
            elif state.halted and not isinstance(action, CancelOrder):
                reason = ReasonCode.HALTED
            elif state.limits_hash is None or not self.checks:
                reason = ReasonCode.MISSING_LIMITS
            else:
                for item in self.checks:
                    outcome = item.check(action, state)
                    if outcome is None:
                        continue
                    if not isinstance(outcome, ReasonCode) or outcome is ReasonCode.ACCEPTED:
                        raise ValueError("checks pass only with None or return a rejection reason")
                    return RiskDecision(accepted=False, reason=outcome, timestamp=clock)
                return RiskDecision(
                    accepted=True,
                    reason=ReasonCode.ACCEPTED,
                    timestamp=clock,
                    authorised=AuthorisedOrder(action=action, limits_hash=state.limits_hash),
                )
            return RiskDecision(accepted=False, reason=reason, timestamp=clock)
        except Exception:
            # Exception text may contain private state. Reject without leaking it,
            # preserving a stable internal-error reason and no authorized action.
            return RiskDecision(accepted=False, reason=ReasonCode.INTERNAL_ERROR, timestamp=clock)
