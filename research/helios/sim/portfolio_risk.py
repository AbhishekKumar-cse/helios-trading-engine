"""Projected position and gross exposure from conservative fill bounds (131)."""

from collections.abc import Callable
from decimal import Decimal, localcontext

from pydantic import Field

from helios.common.types import (
    AmendOrder,
    CancelOrder,
    Identifier,
    OpenOrders,
    OrderAction,
    Position,
    Price,
    ReasonCode,
    Record,
    RiskDecision,
    RiskState,
    Side,
    Timestamp,
)
from helios.sim.price_risk import (
    InstrumentOrderLimits,
    PriceObservation,
    SizePriceLimits,
    SizePriceRisk,
)
from helios.sim.risk import RiskCheck
from helios.sim.strategy import WORKING_STATES


class PositionLimits(InstrumentOrderLimits):
    max_position_notional: Price


class PortfolioLimits(SizePriceLimits):
    instruments: tuple[PositionLimits, ...] = Field(min_length=1)
    max_gross_exposure: Price


class PortfolioSnapshot(Record):
    timestamp: Timestamp
    snapshot_id: Identifier
    positions: tuple[Position, ...]
    open_orders: OpenOrders
    marks: tuple[PriceObservation, ...]


class PortfolioRisk:
    def __init__(
        self,
        config: PortfolioLimits,
        state: Callable[[], RiskState],
        prices: Callable[[str], tuple[PriceObservation, ...]],
        portfolio: Callable[[], PortfolioSnapshot],
    ) -> None:
        self.config = PortfolioLimits.model_validate(config.model_dump())
        self.state, self.prices, self.portfolio = state, prices, portfolio
        self.limits_hash = SizePriceRisk(self.config, state, prices).limits_hash

    def check(self, action: OrderAction) -> RiskDecision:
        histories: dict[str, tuple[PriceObservation, ...]] = {}
        projected: tuple[dict[str, Decimal], ReasonCode | None] | None = None

        def prices(symbol: str) -> tuple[PriceObservation, ...]:
            if symbol not in histories:
                histories[symbol] = self.prices(symbol)
            return histories[symbol]

        def resolve(state: RiskState) -> tuple[dict[str, Decimal], ReasonCode | None]:
            nonlocal projected
            if projected is not None:
                return projected
            if isinstance(action, CancelOrder):
                return {}, None
            view = PortfolioSnapshot.model_validate(self.portfolio().model_dump())
            limits = {i.symbol: i for i in self.config.instruments}
            marks = {m.symbol: m for m in view.marks}
            if (
                view.timestamp != state.timestamp
                or view.snapshot_id != action.lineage.snapshot_id
                or len(marks) != len(view.marks)
                or len({p.symbol for p in view.positions}) != len(view.positions)
                or len({o.order_id for o in view.open_orders}) != len(view.open_orders)
                or any(p.timestamp > state.timestamp for p in view.positions)
            ):
                return {}, ReasonCode.STALE_MARKET_DATA
            active = [o for o in view.open_orders if o.state in WORKING_STATES]
            if any(
                o.timestamp > state.timestamp
                or o.request.mode != action.mode
                or o.request.lineage.snapshot_id != view.snapshot_id
                for o in active
            ):
                return {}, ReasonCode.STALE_MARKET_DATA
            side = action.side if not isinstance(action, AmendOrder) else None
            quantity = action.quantity
            if isinstance(action, AmendOrder):
                original = next((o for o in active if o.order_id == action.order_id), None)
                if (
                    original is None
                    or original.request.symbol != action.symbol
                    or action.quantity <= original.filled_quantity
                ):
                    return {}, ReasonCode.VENUE_REJECTED
                side = original.request.side
                with localcontext() as context:
                    context.prec = 80
                    quantity = action.quantity - original.filled_quantity
                active = [o for o in active if o.order_id != original.order_id]
            symbols = {
                action.symbol,
                *[p.symbol for p in view.positions],
                *[o.request.symbol for o in active],
            }
            if not symbols.issubset(limits):
                return {}, ReasonCode.UNKNOWN_INSTRUMENT
            if not symbols.issubset(marks):
                return {}, ReasonCode.STALE_MARKET_DATA
            for symbol in symbols:
                mark = marks[symbol]
                if (
                    mark.snapshot_id != view.snapshot_id
                    or mark.timestamp > state.timestamp
                    or state.timestamp - mark.timestamp > limits[symbol].max_price_age_us
                ):
                    return {}, ReasonCode.STALE_MARKET_DATA
            last = histories[action.symbol][-1]
            if (marks[action.symbol].price, marks[action.symbol].timestamp) != (
                last.price,
                last.timestamp,
            ):
                return {}, ReasonCode.STALE_MARKET_DATA
            with localcontext() as context:
                context.prec = 80
                bounds = {s: [Decimal(0), Decimal(0)] for s in symbols}
                for position in view.positions:
                    bounds[position.symbol] = [position.quantity, position.quantity]
                for order in active:
                    index = 1 if order.request.side is Side.BUY else 0
                    bounds[order.request.symbol][index] += order.remaining_quantity * (
                        1 if index else -1
                    )
                assert side is not None
                index = 1 if side is Side.BUY else 0
                bounds[action.symbol][index] += quantity * (1 if index else -1)
                notionals = {
                    s: max(abs(low), abs(high))
                    * (
                        max(marks[s].price, action.price or marks[s].price)
                        if s == action.symbol
                        else marks[s].price
                    )
                    for s, (low, high) in bounds.items()
                }
            projected = notionals, None
            return projected

        def position(command: OrderAction, state: RiskState) -> ReasonCode | None:
            if isinstance(command, CancelOrder):
                return None
            notionals, error = resolve(state)
            if error is not None:
                return error
            limits = {i.symbol: i.max_position_notional for i in self.config.instruments}
            return (
                ReasonCode.POSITION_LIMIT
                if any(v > limits[s] for s, v in notionals.items())
                else None
            )

        def exposure(command: OrderAction, state: RiskState) -> ReasonCode | None:
            if isinstance(command, CancelOrder):
                return None
            notionals, error = resolve(state)
            if error is not None:
                return error
            with localcontext() as context:
                context.prec = 80
                total = sum(notionals.values(), Decimal(0))
            return ReasonCode.EXPOSURE_LIMIT if total > self.config.max_gross_exposure else None

        return SizePriceRisk(self.config, self.state, prices).check(
            action,
            additional_checks=(
                RiskCheck("projected_position", position),
                RiskCheck("gross_exposure", exposure),
            ),
        )
