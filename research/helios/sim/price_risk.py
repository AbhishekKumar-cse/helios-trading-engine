"""Configured order notional and causal trailing-median price checks (130)."""

from collections.abc import Callable
from decimal import Decimal, localcontext
from statistics import median
from typing import Annotated, Self

from pydantic import Field, StrictInt, model_validator

from helios.common.config import config_hash
from helios.common.types import (
    CancelOrder,
    Identifier,
    OrderAction,
    Price,
    ReasonCode,
    Record,
    RiskDecision,
    RiskState,
    Timestamp,
)
from helios.sim.risk import CheckChain, RiskCheck


class InstrumentOrderLimits(Record):
    symbol: Identifier
    max_order_notional: Price
    price_band_fraction: Annotated[Decimal, Field(ge=0, le=1, allow_inf_nan=False)]
    median_window: StrictInt = Field(default=24, ge=1)
    max_price_age_us: StrictInt = Field(default=3_600_000_000, ge=0)


class SizePriceLimits(Record):
    instruments: tuple[InstrumentOrderLimits, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self) -> Self:
        if len({i.symbol for i in self.instruments}) != len(self.instruments):
            raise ValueError("instrument limits must be unique")
        return self


class PriceObservation(Record):
    symbol: Identifier
    timestamp: Timestamp  # actual availability clock, not a future bar's open
    price: Price
    snapshot_id: Identifier


class SizePriceRisk:
    """RiskEngine adapter for these checks only; later portfolio/loss checks remain.

    One validated state and one immutable price-history read per check invocation.
    Max-order checks precede price-band checks. Cancels do not create exposure and
    need no price history, but still require the matching applied limits snapshot.
    """

    def __init__(
        self,
        config: SizePriceLimits,
        state: Callable[[], RiskState],
        prices: Callable[[str], tuple[PriceObservation, ...]],
    ) -> None:
        self.config = type(config).model_validate(config.model_dump())
        self.limits_hash = config_hash(self.config)
        self.state, self.prices = state, prices

    def check(
        self, action: OrderAction, *, additional_checks: tuple[RiskCheck, ...] = ()
    ) -> RiskDecision:
        reference: (
            tuple[InstrumentOrderLimits | None, Decimal | None, Decimal | None, ReasonCode | None]
            | None
        ) = None

        def resolve(
            state: RiskState,
        ) -> tuple[InstrumentOrderLimits | None, Decimal | None, Decimal | None, ReasonCode | None]:
            nonlocal reference
            if reference is not None:
                return reference
            limit = next((i for i in self.config.instruments if i.symbol == action.symbol), None)
            if limit is None:
                reference = (None, None, None, ReasonCode.UNKNOWN_INSTRUMENT)
                return reference
            history = tuple(
                PriceObservation.model_validate(p.model_dump()) for p in self.prices(action.symbol)
            )
            times = [p.timestamp for p in history]
            if (
                len(history) < limit.median_window
                or times != sorted(set(times))
                or any(
                    p.timestamp > state.timestamp
                    or p.symbol != action.symbol
                    or p.snapshot_id != action.lineage.snapshot_id
                    for p in history
                )
                or state.timestamp - history[-1].timestamp > limit.max_price_age_us
            ):
                reference = (limit, None, None, ReasonCode.STALE_MARKET_DATA)
            else:
                with localcontext() as context:
                    context.prec = 80
                    middle = median(p.price for p in history[-limit.median_window :])
                reference = (limit, history[-1].price, middle, None)
            return reference

        def binding(command: OrderAction, state: RiskState) -> ReasonCode | None:
            return None if state.limits_hash == self.limits_hash else ReasonCode.MISSING_LIMITS

        def size(command: OrderAction, state: RiskState) -> ReasonCode | None:
            if isinstance(command, CancelOrder):
                return None
            limit, latest, _, error = resolve(state)
            if error is not None:
                return error
            assert limit is not None and latest is not None
            with localcontext() as context:
                context.prec = 80
                notional = command.quantity * max(latest, command.price or latest)
            return ReasonCode.MAX_ORDER_SIZE if notional > limit.max_order_notional else None

        def band(command: OrderAction, state: RiskState) -> ReasonCode | None:
            if isinstance(command, CancelOrder):
                return None
            limit, latest, middle, error = resolve(state)
            if error is not None:
                return error
            assert limit is not None and latest is not None and middle is not None
            price = command.price or latest
            with localcontext() as context:
                context.prec = 80
                lower = middle * (1 - limit.price_band_fraction)
                upper = middle * (1 + limit.price_band_fraction)
            return None if lower <= price <= upper else ReasonCode.PRICE_BAND

        return CheckChain(
            (
                RiskCheck("limits_snapshot", binding),
                RiskCheck("max_order_notional", size),
                RiskCheck("median_price_band", band),
            )
            + additional_checks,
            self.state,
        ).check(action)
