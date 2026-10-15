"""Latched daily-loss/manual kill control with durable append-only events (132)."""

from collections.abc import Callable
from threading import Event
from typing import Protocol
from uuid import uuid4

from pydantic import Field
from sqlalchemy import Connection, Engine, text

from helios.common.config import canonical_json, config_hash
from helios.common.types import (
    CancelOrder,
    Hash,
    Identifier,
    OrderAction,
    Price,
    ReasonCode,
    Record,
    RiskDecision,
    RiskState,
    Timestamp,
)
from helios.sim.portfolio_risk import PortfolioLimits, PortfolioRisk, PortfolioSnapshot
from helios.sim.price_risk import PriceObservation


class DailyRiskLimits(PortfolioLimits):
    scope: Identifier
    daily_loss_limit: Price


class RiskTrip(Record):
    scope: Identifier
    timestamp: Timestamp
    reason: ReasonCode
    limits_hash: Hash
    actor: str = Field(min_length=2)


def tripped(connection: Connection, scope: str) -> bool:
    return bool(
        connection.execute(
            text(
                "SELECT EXISTS(SELECT 1 FROM risk_events "
                "WHERE subject_ref=:scope AND type='KILL_SWITCH_TRIPPED')"
            ),
            {"scope": scope},
        ).scalar_one()
    )


def record_trip(connection: Connection, event: RiskTrip) -> None:
    connection.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:scope))"),
        {"scope": "helios_kill:" + event.scope},
    )
    if tripped(connection, event.scope):
        return
    connection.execute(
        text(
            "INSERT INTO risk_events "
            "(event_id,ts,type,severity,reason_code,subject_ref,limits_snapshot_hash,actor) "
            "VALUES (:id,:ts,'KILL_SWITCH_TRIPPED','CRITICAL',:reason,:scope,:hash,:actor)"
        ),
        dict(
            id=str(uuid4()),
            ts=event.timestamp,
            reason=event.reason.value,
            scope=event.scope,
            hash=event.limits_hash,
            actor=event.actor,
        ),
    )
    connection.execute(
        text("""INSERT INTO audit_events
        (ts,actor,action,subject,after_hash,justification,payload)
        VALUES (:ts,:actor,'KILL_SWITCH_TRIPPED',:scope,:hash,:reason,CAST(:payload AS jsonb))"""),
        dict(
            ts=event.timestamp,
            actor=event.actor,
            scope=event.scope,
            hash=config_hash(event),
            reason=event.reason.value,
            payload=canonical_json(event),
        ),
    )


class TripStore(Protocol):
    def is_tripped(self, scope: str) -> bool: ...
    def trip(self, event: RiskTrip) -> None: ...


class PostgresTripStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def is_tripped(self, scope: str) -> bool:
        with self.engine.connect() as connection:
            return tripped(connection, scope)

    def trip(self, event: RiskTrip) -> None:
        with self.engine.begin() as connection:
            record_trip(connection, event)


class DailyRisk:
    def __init__(
        self,
        config: DailyRiskLimits,
        state: Callable[[], RiskState],
        prices: Callable[[str], tuple[PriceObservation, ...]],
        portfolio: Callable[[], PortfolioSnapshot],
        store: TripStore,
    ) -> None:
        self.config = DailyRiskLimits.model_validate(config.model_dump())
        self.limits_hash = config_hash(self.config)
        self.state, self.prices, self.portfolio, self.store = state, prices, portfolio, store
        self._halted = Event()

    def trip(self, timestamp: int, actor: str, reason: ReasonCode = ReasonCode.HALTED) -> None:
        event = RiskTrip(
            scope=self.config.scope,
            timestamp=timestamp,
            actor=actor,
            reason=reason,
            limits_hash=self.limits_hash,
        )
        if reason not in (ReasonCode.HALTED, ReasonCode.DAILY_LOSS_LIMIT):
            raise ValueError("kill trip requires manual halt or daily loss reason")
        self._halted.set()  # independent of a blocked strategy/provider or journal
        self.store.trip(event)  # success means committed; failure remains latched locally

    def check(self, action: OrderAction) -> RiskDecision:
        clock = action.timestamp
        try:
            halted = self._halted.is_set() or self.store.is_tripped(self.config.scope)
            if halted:
                self._halted.set()
                if not isinstance(action, CancelOrder):
                    return RiskDecision(accepted=False, reason=ReasonCode.HALTED, timestamp=clock)
            state = RiskState.model_validate(self.state().model_dump())
            clock = state.timestamp
            if clock < action.timestamp:
                return RiskDecision(
                    accepted=False, reason=ReasonCode.STALE_MARKET_DATA, timestamp=action.timestamp
                )
            if state.limits_hash != self.limits_hash:
                return RiskDecision(
                    accepted=False, reason=ReasonCode.MISSING_LIMITS, timestamp=clock
                )
            if state.halted and not isinstance(action, CancelOrder):
                self.trip(clock, "risk_state")
                return RiskDecision(accepted=False, reason=ReasonCode.HALTED, timestamp=clock)
            if state.daily_pnl <= self.config.daily_loss_limit.copy_negate() and not isinstance(
                action, CancelOrder
            ):
                self.trip(clock, "daily_loss_guard", ReasonCode.DAILY_LOSS_LIMIT)
                return RiskDecision(
                    accepted=False, reason=ReasonCode.DAILY_LOSS_LIMIT, timestamp=clock
                )
            result = PortfolioRisk(self.config, lambda: state, self.prices, self.portfolio).check(
                action
            )
            if not isinstance(action, CancelOrder) and (
                self._halted.is_set() or self.store.is_tripped(self.config.scope)
            ):
                return RiskDecision(accepted=False, reason=ReasonCode.HALTED, timestamp=clock)
            return result
        except Exception:
            return RiskDecision(accepted=False, reason=ReasonCode.INTERNAL_ERROR, timestamp=clock)
