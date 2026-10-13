"""Structural boundaries from architecture section 8; no runtime implementation (113)."""

from collections.abc import Callable, Iterator
from typing import Protocol, runtime_checkable

from helios.alpha.definition import AlphaDefinition
from helios.common.types import (
    Ack,
    AlphaValue,
    AmendOrder,
    BookView,
    CancelOrder,
    ExecutionReport,
    FeatureVector,
    MarketEvent,
    NewOrder,
    OpenOrders,
    OrderAction,
    Position,
    Reject,
    RiskDecision,
    RiskState,
    VenueInfo,
    VenueOrderView,
)


@runtime_checkable
class MarketDataSource(Protocol):
    def events(self) -> Iterator[MarketEvent]: ...


@runtime_checkable
class AlphaModel(Protocol):
    @property
    def definition(self) -> AlphaDefinition: ...

    def value(self, fv: FeatureVector) -> AlphaValue: ...


@runtime_checkable
class Strategy(Protocol):
    def on_update(
        self,
        alpha: AlphaValue,
        book: BookView,
        pos: Position,
        open_orders: OpenOrders,
        risk: RiskState,
    ) -> list[OrderAction]: ...


@runtime_checkable
class RiskEngine(Protocol):
    def check(self, action: OrderAction) -> RiskDecision: ...


@runtime_checkable
class ExecutionVenue(Protocol):
    def submit(self, o: NewOrder) -> Ack | Reject: ...

    def cancel(self, c: CancelOrder) -> Ack | Reject: ...

    def amend(self, a: AmendOrder) -> Ack | Reject: ...

    def subscribe_reports(self, cb: Callable[[ExecutionReport], None]) -> None: ...

    def snapshot_open_orders(self) -> list[VenueOrderView]: ...

    def venue_info(self) -> VenueInfo: ...
