"""Fixed capital allocation and bar strategy intents; no venue submission (122)."""

import hashlib
from decimal import ROUND_DOWN, Decimal, localcontext
from typing import Annotated, Literal

from pydantic import Field

from helios.common.config import canonical_json
from helios.common.types import (
    AlphaStatus,
    AlphaValue,
    BookView,
    DecisionLineage,
    Identifier,
    Mode,
    Money,
    NewOrder,
    OpenOrders,
    OrderAction,
    OrderState,
    OrderType,
    Position,
    Price,
    Record,
    RiskState,
    Side,
    TimeInForce,
    Timestamp,
)

PRECISION = Decimal("0.000000000000000001")


class TargetConfig(Record):
    capital: Price
    max_weight: Annotated[
        Decimal, Field(gt=0, le=1, allow_inf_nan=False, max_digits=38, decimal_places=18)
    ]


class TargetNotional(Record):
    symbol: Identifier
    timestamp: Timestamp
    notional: Money
    lineage: DecisionLineage


def target_notional(alpha: AlphaValue, config: TargetConfig) -> TargetNotional | None:
    """Signed per-coin target = capital * max_weight * bounded alpha.

    Unavailable/stale signals produce no target, not a silently substituted zero.
    Currency rounding is toward zero at the shared numeric(38,18) boundary.
    Portfolio/exposure authorization is independently enforced by later risk checks.
    """
    if alpha.status is not AlphaStatus.OK or alpha.value is None:
        return None
    with localcontext() as context:
        context.prec = 80
        target = (config.capital * config.max_weight * Decimal(str(alpha.value))).quantize(
            PRECISION, rounding=ROUND_DOWN
        )
    return TargetNotional(
        symbol=alpha.symbol, timestamp=alpha.timestamp, notional=target, lineage=alpha.lineage
    )


class BarStrategyConfig(TargetConfig):
    strategy_id: Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]+$")]
    rebalance_threshold: Annotated[Decimal, Field(ge=0, le=1, allow_inf_nan=False)]
    mode: Literal[Mode.BACKTEST, Mode.REPLAY, Mode.PAPER] = Mode.BACKTEST


WORKING_STATES = frozenset(
    (
        OrderState.CREATED,
        OrderState.PENDING_NEW,
        OrderState.ACCEPTED,
        OrderState.PARTIALLY_FILLED,
        OrderState.PENDING_CANCEL,
        OrderState.PENDING_AMEND,
    )
)


class BarStrategy:
    def __init__(self, config: BarStrategyConfig) -> None:
        self.config = BarStrategyConfig.model_validate(config.model_dump())

    def on_update(
        self,
        alpha: AlphaValue,
        book: BookView,
        pos: Position,
        open_orders: OpenOrders,
        risk: RiskState,
    ) -> list[OrderAction]:
        """Generate an idempotent market intent from the projected position.

        Working remaining quantities count toward exposure, including pending
        cancellation until confirmed. Threshold is a fraction of configured
        capital, not price or alpha. No submission or fill occurs here.
        """
        if alpha.symbol != book.symbol or alpha.symbol != pos.symbol:
            raise ValueError("strategy input symbols disagree")
        if len({o.order_id for o in open_orders}) != len(open_orders):
            raise ValueError("duplicate working order")
        if any(
            o.request.symbol != alpha.symbol
            or o.request.mode != self.config.mode
            or o.request.lineage.snapshot_id != alpha.lineage.snapshot_id
            for o in open_orders
        ):
            raise ValueError("working orders require matching symbol, mode and snapshot")
        if (
            risk.halted
            or risk.limits_hash is None
            or book.stale
            or book.timestamp != alpha.timestamp
            or risk.timestamp != alpha.timestamp
            or pos.timestamp > alpha.timestamp
            or any(o.timestamp > alpha.timestamp for o in open_orders)
            or book.best_bid is None
            or book.best_ask is None
        ):
            return []
        target = target_notional(alpha, self.config)
        if target is None:
            return []
        with localcontext() as context:
            context.prec = 80
            reference = (book.best_bid + book.best_ask) / 2
            projected = pos.quantity + sum(
                (
                    o.remaining_quantity * (1 if o.request.side is Side.BUY else -1)
                    for o in open_orders
                    if o.state in WORKING_STATES
                ),
                Decimal(0),
            )
            delta = target.notional / reference - projected
            if (
                delta == 0
                or abs(delta * reference) < self.config.capital * self.config.rebalance_threshold
            ):
                return []
            quantity = abs(delta).quantize(PRECISION, rounding=ROUND_DOWN)
        if quantity == 0:
            return []
        payload = "|".join(
            (
                canonical_json(self.config),
                alpha.model_dump_json(),
                book.model_dump_json(),
                pos.model_dump_json(),
                *(o.model_dump_json() for o in sorted(open_orders, key=lambda o: o.order_id)),
            )
        )
        identifier = hashlib.sha256(payload.encode()).hexdigest()
        return [
            NewOrder(
                client_order_id=identifier,
                strategy_id=self.config.strategy_id,
                symbol=alpha.symbol,
                side=Side.BUY if delta > 0 else Side.SELL,
                order_type=OrderType.MARKET,
                quantity=quantity,
                price=None,
                time_in_force=TimeInForce.IOC,
                timestamp=alpha.timestamp,
                lineage=alpha.lineage,
                mode=self.config.mode,
            )
        ]
