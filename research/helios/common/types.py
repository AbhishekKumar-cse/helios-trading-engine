"""Immutable Python event and command boundaries; simulated execution only (112).

Money/quantities are finite Decimal values, not implicit C++ ticks/lots. Runtime
risk authorization, reconciliation and state transitions are later components.
"""

from __future__ import annotations

from decimal import Decimal, localcontext
from enum import StrEnum
from math import isfinite
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    StrictBool,
    field_validator,
    model_serializer,
    model_validator,
)

from helios.common.project_config import HorizonFamily
from helios.data.klines import interval_us

Timestamp = Annotated[int, Field(strict=True, ge=0, lt=2**63)]
Identifier = Annotated[str, Field(min_length=1)]
Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Price = Annotated[Decimal, Field(gt=0, allow_inf_nan=False, max_digits=38, decimal_places=18)]
Quantity = Annotated[Decimal, Field(gt=0, allow_inf_nan=False, max_digits=38, decimal_places=18)]
NonNegative = Annotated[Decimal, Field(ge=0, allow_inf_nan=False, max_digits=38, decimal_places=18)]
Money = Annotated[Decimal, Field(allow_inf_nan=False, max_digits=38, decimal_places=18)]
Sequence = Annotated[int, Field(strict=True, ge=0)]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


class Mode(StrEnum):
    BACKTEST = "BACKTEST"
    REPLAY = "REPLAY"
    PAPER = "PAPER"


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class TimeInForce(StrEnum):
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"


class OrderState(StrEnum):
    CREATED = "NEW"  # migration 005's persisted spelling
    PENDING_NEW = "PENDING_NEW"
    ACCEPTED = "ACK"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    PENDING_CANCEL = "PENDING_CANCEL"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    PENDING_AMEND = "PENDING_AMEND"


class AlphaStatus(StrEnum):
    OK = "OK"
    UNAVAILABLE = "UNAVAILABLE"
    STALE = "STALE"


class ReasonCode(StrEnum):
    ACCEPTED = "ACCEPTED"
    HALTED = "HALTED"
    UNKNOWN_INSTRUMENT = "UNKNOWN_INSTRUMENT"
    STALE_ALPHA = "STALE_ALPHA"
    STALE_MARKET_DATA = "STALE_MARKET_DATA"
    MISSING_LIMITS = "MISSING_LIMITS"
    MAX_ORDER_SIZE = "MAX_ORDER_SIZE"
    PRICE_BAND = "PRICE_BAND"
    POSITION_LIMIT = "POSITION_LIMIT"
    EXPOSURE_LIMIT = "EXPOSURE_LIMIT"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    UNSUPPORTED_AMEND = "UNSUPPORTED_AMEND"
    VENUE_REJECTED = "VENUE_REJECTED"


class DecisionLineage(Record):
    alpha_id: Identifier
    alpha_version: Annotated[int, Field(strict=True, ge=1)]
    feature_set_version: Identifier
    horizon_family: HorizonFamily
    code_commit: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    config_hash: Hash
    snapshot_id: Identifier

    seed: Annotated[int, Field(strict=True, ge=0, le=2**32 - 1)]
    model_hash: Hash | None = None


class Bar(Record):
    calendar: Literal["continuous_utc", "nse_regular_v1", "nse_reviewed_v2"] = "continuous_utc"

    @model_serializer(mode="wrap")
    def _calendar_serialization(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        if self.calendar == "continuous_utc":
            data.pop("calendar", None)
        return data

    symbol: Identifier
    source: Identifier
    sequence: Sequence
    open_time: Timestamp
    ingest_time: Timestamp
    interval: Literal["1h", "1m"]
    open: Price
    high: Price
    low: Price
    close: Price
    volume: NonNegative
    snapshot_id: Identifier
    recorded_close_time: Timestamp | None = None
    close_time_resolution_us: Literal[1, 1000] = 1

    @field_validator("close_time_resolution_us", mode="before")
    @classmethod
    def _precision(cls, value: object) -> object:
        if type(value) is not int or value not in (1, 1000):
            raise ValueError("close timestamp precision must be 1 or 1000 microseconds")
        return value

    @property
    def close_time(self) -> int:
        """Exclusive bar end; decision is available only after the interval closes."""
        return (
            self.open_time + interval_us(self.interval)
            if self.recorded_close_time is None
            else self.recorded_close_time + self.close_time_resolution_us
        )

    @property
    def is_complete_interval(self) -> bool:
        if self.calendar == "nse_reviewed_v2":
            from helios.common.market_clock import nse_reviewed_bar_complete

            return nse_reviewed_bar_complete(self.open_time, self.close_time, self.interval)
        if self.calendar == "nse_regular_v1":
            from helios.common.market_clock import nse_bar_complete

            return nse_bar_complete(self.open_time, self.close_time, self.interval)
        period = interval_us(self.interval)
        return self.open_time % period == 0 and self.close_time - self.open_time == period

    @model_validator(mode="after")
    def _bar(self) -> Self:
        if (
            self.high < max(self.open, self.close)
            or self.low > min(self.open, self.close)
            or self.low > self.high
        ):
            raise ValueError("OHLC prices must lie inside low/high")
        if self.close_time >= 2**63 or self.ingest_time < self.close_time:
            raise ValueError("bar ingest must be at/after its representable closing boundary")
        if self.close_time <= self.open_time:
            raise ValueError("recorded bar end must follow its opening time")
        return self


MarketEvent = Bar  # fifth-semester bar events; LOB events require explicit later adapters


class FeatureValue(Record):
    name: Identifier
    value: float | None
    available: StrictBool

    @field_validator("value", mode="before")
    @classmethod
    def _not_boolean(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("feature value cannot be boolean")
        return value

    @model_validator(mode="after")
    def _availability(self) -> Self:
        if self.available != (self.value is not None):
            raise ValueError("unavailable features must have value None")
        if self.value is not None and not isfinite(self.value):
            raise ValueError("available feature must be finite")
        return self


class FeatureVector(Record):
    symbol: Identifier
    timestamp: Timestamp
    feature_set_version: Identifier
    snapshot_id: Identifier
    features: tuple[FeatureValue, ...]

    @model_validator(mode="after")
    def _names(self) -> Self:
        if len({f.name for f in self.features}) != len(self.features):
            raise ValueError("feature names must be unique")
        return self


class AlphaValue(Record):
    symbol: Identifier
    timestamp: Timestamp
    status: AlphaStatus
    value: Annotated[float, Field(ge=-1, le=1, allow_inf_nan=False)] | None
    lineage: DecisionLineage

    @field_validator("value", mode="before")
    @classmethod
    def _not_boolean(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("alpha value cannot be boolean")
        return value

    @model_validator(mode="after")
    def _status(self) -> Self:
        if (self.status is AlphaStatus.OK) != (self.value is not None):
            raise ValueError("only OK alpha may carry an actionable value")
        return self


class NewOrder(Record):
    kind: Literal["new"] = "new"
    client_order_id: Identifier
    strategy_id: Identifier
    symbol: Identifier
    side: Side
    order_type: OrderType
    quantity: Quantity
    price: Price | None = None
    time_in_force: TimeInForce
    timestamp: Timestamp
    lineage: DecisionLineage
    mode: Mode

    @model_validator(mode="after")
    def _price(self) -> Self:
        if (self.order_type is OrderType.LIMIT) != (self.price is not None):
            raise ValueError("LIMIT requires a price; MARKET carries no limit price")
        return self


class CancelOrder(Record):
    kind: Literal["cancel"] = "cancel"
    request_id: Identifier
    order_id: Identifier
    symbol: Identifier
    timestamp: Timestamp
    lineage: DecisionLineage
    mode: Mode


class AmendOrder(Record):
    kind: Literal["amend"] = "amend"
    request_id: Identifier
    order_id: Identifier
    symbol: Identifier
    quantity: Quantity  # new total quantity, not the remaining quantity
    price: Price
    timestamp: Timestamp
    lineage: DecisionLineage
    mode: Mode


OrderAction = Annotated[NewOrder | CancelOrder | AmendOrder, Field(discriminator="kind")]


class Order(Record):
    order_id: Identifier
    request: NewOrder
    state: OrderState
    filled_quantity: NonNegative
    remaining_quantity: NonNegative
    timestamp: Timestamp

    @model_validator(mode="after")
    def _conservation(self) -> Self:
        with localcontext() as context:
            context.prec = 80  # exact addition throughout numeric(38,18)'s domain
            if self.filled_quantity + self.remaining_quantity != self.request.quantity:
                raise ValueError("filled + remaining must equal order quantity")
        if self.state is OrderState.FILLED and self.remaining_quantity != 0:
            raise ValueError("FILLED requires zero remaining quantity")
        if (
            self.state is OrderState.PARTIALLY_FILLED
            and not 0 < self.filled_quantity < self.request.quantity
        ):
            raise ValueError("partial fill requires both filled and remaining quantities")
        if (
            self.state in (OrderState.CREATED, OrderState.PENDING_NEW, OrderState.ACCEPTED)
            and self.filled_quantity != 0
        ):
            raise ValueError("unfilled order state cannot carry fills")
        if self.remaining_quantity == 0 and self.state is not OrderState.FILLED:
            raise ValueError("completely filled order requires FILLED state")
        if self.timestamp < self.request.timestamp:
            raise ValueError("order update cannot precede its decision")
        return self


class Fill(Record):
    fill_id: Identifier
    order_id: Identifier
    symbol: Identifier
    side: Side
    quantity: Quantity
    price: Price
    fee: NonNegative
    fee_asset: Identifier
    timestamp: Timestamp
    venue_id: Identifier
    liquidity: Literal["MAKER", "TAKER"]
    mode: Mode


class ExecutionReport(Record):
    order_id: Identifier
    client_order_id: Identifier
    sequence: Sequence
    timestamp: Timestamp
    state: OrderState
    filled_quantity: NonNegative
    remaining_quantity: NonNegative
    fill: Fill | None = None
    reason: ReasonCode | None = None

    @model_validator(mode="after")
    def _report(self) -> Self:
        if self.fill is not None and (
            self.fill.order_id != self.order_id or self.fill.quantity > self.filled_quantity
        ):
            raise ValueError("fill must belong to this order and fit cumulative filled quantity")
        if self.state is OrderState.REJECTED and (
            self.reason is None or self.reason is ReasonCode.ACCEPTED
        ):
            raise ValueError("rejected report requires a rejection reason")
        if self.state is OrderState.FILLED and self.remaining_quantity != 0:
            raise ValueError("filled report requires zero remaining quantity")
        if self.state is OrderState.PARTIALLY_FILLED and (
            self.filled_quantity == 0 or self.remaining_quantity == 0
        ):
            raise ValueError("partial report requires filled and remaining quantities")
        return self


class Position(Record):
    symbol: Identifier
    quantity: Money  # signed base-asset quantity; short positions are negative
    average_entry_price: Price | None
    timestamp: Timestamp

    @model_validator(mode="after")
    def _entry(self) -> Self:
        if (self.quantity != 0) != (self.average_entry_price is not None):
            raise ValueError("non-flat position requires average entry price; flat has None")
        return self


class PnLSnapshot(Record):
    timestamp: Timestamp
    quote_asset: Identifier
    cash: Money
    equity: Money
    realized_pnl: Money
    unrealized_pnl: Money
    fees: NonNegative
    mode: Mode
    config_hash: Hash


class AuthorisedOrder(Record):
    action: OrderAction
    limits_hash: Hash


class RiskDecision(Record):
    accepted: StrictBool
    reason: ReasonCode
    timestamp: Timestamp
    authorised: AuthorisedOrder | None = None

    @model_validator(mode="after")
    def _decision(self) -> Self:
        if self.accepted != (self.authorised is not None) or self.accepted != (
            self.reason is ReasonCode.ACCEPTED
        ):
            raise ValueError(
                "accept requires authorised action/limits hash; reject must carry neither"
            )
        return self


class BookView(Record):
    symbol: Identifier
    timestamp: Timestamp
    sequence: Sequence
    best_bid: Price | None
    best_ask: Price | None
    stale: StrictBool

    @model_validator(mode="after")
    def _spread(self) -> Self:
        if (
            self.best_bid is not None
            and self.best_ask is not None
            and self.best_bid > self.best_ask
        ):
            raise ValueError("book must not be crossed")
        return self


OpenOrders = tuple[Order, ...]
VenueOrderView = Order


class RiskState(Record):
    timestamp: Timestamp
    halted: StrictBool
    daily_pnl: Money
    limits_hash: Hash | None


class Ack(Record):
    request_id: Identifier
    order_id: Identifier
    timestamp: Timestamp


class Reject(Record):
    request_id: Identifier
    reason: ReasonCode
    timestamp: Timestamp

    @model_validator(mode="after")
    def _reject(self) -> Self:
        if self.reason is ReasonCode.ACCEPTED:
            raise ValueError("reject cannot have ACCEPTED reason")
        return self


class VenueInfo(Record):
    venue_id: Identifier
    is_simulated: Literal[True] = True
    supports_amend: StrictBool

    @field_validator("is_simulated", mode="before")
    @classmethod
    def _simulated(cls, value: object) -> object:
        if value is not True:
            raise ValueError("only explicitly simulated venues are supported")
        return value
