"""Deterministic, session-scoped bar venue. All execution is simulated (141).

Full market fills assume unlimited liquidity and no impact/queue model. Commands
acknowledge acceptance only; report delivery is an explicit event-loop operation.
"""

from collections.abc import Callable
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import TypeAdapter

from helios.common.config import config_hash
from helios.common.project_config import FeesConfig, load_fees
from helios.common.types import (
    Ack,
    AmendOrder,
    Bar,
    CancelOrder,
    ExecutionReport,
    Fill,
    Mode,
    NewOrder,
    Order,
    OrderState,
    Price,
    ReasonCode,
    Reject,
    Side,
    TimeInForce,
    Timestamp,
    VenueInfo,
)
from helios.sim.event_loop import BarOpen

SCALE = Decimal("1e-18")
TERMINAL = frozenset((OrderState.FILLED, OrderState.CANCELLED, OrderState.EXPIRED))


def rounded(value: Decimal) -> Decimal:
    """Explicit numeric(38,18) rounding, independent of the caller's context."""
    with localcontext() as context:
        context.prec = 100
        return value.quantize(SCALE, rounding=ROUND_HALF_EVEN)


class BarPaperVenue:
    def __init__(
        self, mode: Mode, fees: FeesConfig | None = None, venue_id: str = "bar-paper"
    ) -> None:
        self.mode = Mode(mode)
        self._info = VenueInfo(venue_id=venue_id, supports_amend=False)
        selected = load_fees() if fees is None else fees
        self._fees = FeesConfig.model_validate(selected.model_dump())
        if any(bps >= 10000 for bps in self._fees.slippage_bps.values()):
            raise ValueError("slippage must be less than 10000 bps")
        self.fees_hash = config_hash(self._fees)
        self._orders: dict[str, Order] = {}
        self._clients: dict[str, str] = {}
        self._acks: dict[str, Ack] = {}
        self._sequence: dict[str, int] = {}
        self._opens: dict[str, BarOpen] = {}
        self._callbacks: list[Callable[[ExecutionReport], None]] = []
        self._outbox: list[ExecutionReport] = []
        self._cancels: dict[str, tuple[CancelOrder, Ack]] = {}
        self._resting: dict[str, BarOpen] = {}
        self._closed: dict[str, int] = {}
        self._clock: dict[str, int] = {}

    def venue_info(self) -> VenueInfo:
        return self._info

    def subscribe_reports(self, cb: Callable[[ExecutionReport], None]) -> None:
        self._callbacks.append(cb)

    def dispatch_reports(self) -> None:
        """Drain after OMS has entered PENDING_NEW; consumers must deduplicate."""
        if not self._callbacks:
            return
        while self._outbox:
            report = self._outbox[0]
            for cb in tuple(self._callbacks):
                cb(report)
            self._outbox.pop(0)

    def snapshot_open_orders(self) -> list[Order]:
        return [o for o in self._orders.values() if o.state not in TERMINAL]

    def _reject(self, request_id: str, timestamp: int) -> Reject:
        return Reject(request_id=request_id, timestamp=timestamp, reason=ReasonCode.VENUE_REJECTED)

    def submit(self, o: NewOrder) -> Ack | Reject:
        return self._submit(o, None)

    def submit_order(self, order: Order) -> Ack | Reject:
        """Preserve an existing OMS identity across the venue boundary."""
        order = Order.model_validate(order.model_dump())
        if order.state is not OrderState.PENDING_NEW:
            raise ValueError("venue handoff requires PENDING_NEW")
        return self._submit(order.request, order.order_id, order.timestamp)

    def _submit(
        self, o: NewOrder, order_id: str | None, received_at: int | None = None
    ) -> Ack | Reject:
        o = NewOrder.model_validate(o.model_dump())
        timestamp = o.timestamp if received_at is None else received_at
        prior_id = self._clients.get(o.client_order_id)
        if prior_id is not None:
            prior = self._orders[prior_id]
            if prior.request != o or (order_id is not None and prior_id != order_id):
                return self._reject(o.client_order_id, o.timestamp)
            return self._acks[prior_id]
        opening = self._opens.get(o.symbol)
        if (
            o.mode != self.mode
            or o.symbol not in self._fees.slippage_bps
            or not o.symbol.endswith("USDT")
            or timestamp < self._clock.get(o.symbol, 0)
            or timestamp < o.timestamp
            or (opening is not None and timestamp <= opening.timestamp)
        ):
            return self._reject(o.client_order_id, o.timestamp)
        identifier = (
            order_id
            if order_id is not None
            else f"paper_{uuid5(NAMESPACE_URL, self._info.venue_id + ':' + o.client_order_id).hex}"
        )
        if identifier in self._orders:
            return self._reject(o.client_order_id, o.timestamp)
        order = Order(
            order_id=identifier,
            request=o,
            state=OrderState.ACCEPTED,
            filled_quantity=Decimal(0),
            remaining_quantity=o.quantity,
            timestamp=timestamp,
        )
        self._clients[o.client_order_id] = identifier
        self._orders[identifier] = order
        self._clock[o.symbol] = timestamp
        self._report(order)
        ack = Ack(request_id=o.client_order_id, order_id=identifier, timestamp=timestamp)
        self._acks[identifier] = ack
        return ack

    def _report(self, order: Order, fill: Fill | None = None) -> None:
        sequence = self._sequence.get(order.order_id, -1) + 1
        report = ExecutionReport(
            order_id=order.order_id,
            client_order_id=order.request.client_order_id,
            sequence=sequence,
            timestamp=order.timestamp,
            state=order.state,
            filled_quantity=order.filled_quantity,
            remaining_quantity=order.remaining_quantity,
            fill=fill,
        )
        self._orders[order.order_id] = order
        self._sequence[order.order_id] = sequence
        self._outbox.append(report)

    def cancel(self, c: CancelOrder) -> Ack | Reject:
        c = CancelOrder.model_validate(c.model_dump())
        prior = self._cancels.get(c.request_id)
        if prior is not None:
            return prior[1] if prior[0] == c else self._reject(c.request_id, c.timestamp)
        order = self._orders.get(c.order_id)
        opening = self._opens.get(c.symbol)
        if (
            order is None
            or order.state in TERMINAL
            or c.mode != self.mode
            or c.symbol != order.request.symbol
            or c.lineage != order.request.lineage
            or c.timestamp < order.timestamp
            or c.timestamp < self._clock.get(c.symbol, 0)
            or (opening is not None and c.timestamp < opening.timestamp)
            or (
                c.order_id in self._resting
                and opening is not None
                and c.timestamp > opening.timestamp
            )
        ):
            return self._reject(c.request_id, c.timestamp)
        changed = Order.model_validate(
            order.model_dump() | dict(state=OrderState.CANCELLED, timestamp=c.timestamp)
        )
        self._report(changed)
        self._clock[c.symbol] = c.timestamp
        self._resting.pop(c.order_id, None)
        ack = Ack(request_id=c.request_id, order_id=c.order_id, timestamp=c.timestamp)
        self._cancels[c.request_id] = (c, ack)
        return ack

    def amend(self, a: AmendOrder) -> Ack | Reject:
        a = AmendOrder.model_validate(a.model_dump())
        return Reject(
            request_id=a.request_id, timestamp=a.timestamp, reason=ReasonCode.UNSUPPORTED_AMEND
        )

    def _filled(
        self,
        order: Order,
        price: Decimal,
        timestamp: int,
        liquidity: Literal["MAKER", "TAKER"] = "TAKER",
    ) -> tuple[Order, Fill]:
        with localcontext() as context:
            context.prec = 100
            fee = rounded(
                price
                * order.remaining_quantity
                * Decimal(
                    str(
                        self._fees.maker_fee_bps
                        if liquidity == "MAKER"
                        else self._fees.taker_fee_bps
                    )
                )
                / 10000
            )
        fill = Fill(
            fill_id=f"{order.order_id}:fill",
            order_id=order.order_id,
            symbol=order.request.symbol,
            side=order.request.side,
            quantity=order.remaining_quantity,
            price=price,
            fee=fee,
            fee_asset="USDT",
            timestamp=timestamp,
            venue_id=self._info.venue_id,
            liquidity=liquidity,
            mode=self.mode,
        )
        changed = Order.model_validate(
            order.model_dump()
            | dict(
                state=OrderState.FILLED,
                filled_quantity=order.request.quantity,
                remaining_quantity=Decimal(0),
                timestamp=timestamp,
            )
        )
        return changed, fill

    def on_open(self, opening: BarOpen) -> None:
        """Only opening price is visible; no high/low/close enters market fills."""
        TypeAdapter(Price).validate_python(opening.price)
        TypeAdapter(Timestamp).validate_python(opening.timestamp)
        if opening.timestamp < self._clock.get(opening.symbol, 0):
            raise ValueError("opening clock precedes an observed command or bar")
        old = self._opens.get(opening.symbol)
        if old is not None and (
            opening.timestamp <= old.timestamp or opening.snapshot_id != old.snapshot_id
        ):
            raise ValueError("opening clock must advance within one snapshot")
        if any(self._orders[key].request.symbol == opening.symbol for key in self._resting):
            raise ValueError("complete the previous resting-order bar before another opening")
        if opening.timestamp < self._closed.get(opening.symbol, 0):
            raise ValueError("opening precedes completed-bar availability")
        ready = [
            o
            for o in self.snapshot_open_orders()
            if o.request.symbol == opening.symbol and o.timestamp <= opening.timestamp
        ]
        if any(o.request.lineage.snapshot_id != opening.snapshot_id for o in ready):
            raise ValueError("opening and order snapshot mismatch")
        fills = []
        resting = []
        expired = []
        for order in ready:
            with localcontext() as context:
                context.prec = 100
                slip = Decimal(str(self._fees.slippage_bps[opening.symbol])) / 10000
                direction = 1 if order.request.side is Side.BUY else -1
                price = rounded(opening.price * (1 + direction * slip))
            limit = order.request.price
            if limit is not None:
                crosses = opening.price < limit if direction == 1 else opening.price > limit
                if not crosses:
                    if order.request.time_in_force is TimeInForce.GTC:
                        resting.append(order.order_id)
                    else:
                        expired.append(
                            Order.model_validate(
                                order.model_dump()
                                | dict(
                                    state=OrderState.EXPIRED,
                                    timestamp=opening.timestamp,
                                )
                            )
                        )
                    continue
                price = min(price, limit) if direction == 1 else max(price, limit)
            fills.append(self._filled(order, price, opening.timestamp))
        self._opens[opening.symbol] = opening
        self._clock[opening.symbol] = opening.timestamp
        self._resting.update({key: opening for key in resting})
        for order in expired:
            self._report(order)
        for changed, fill in fills:
            self._report(changed, fill)
        self.dispatch_reports()

    def on_bar(self, bar: Bar) -> None:
        """Resolve passive fills only after a complete bar's range is available.

        No intrabar path or touch timestamp is inferred. Midbar cancellation is
        refused while range execution is unresolved; cancel at a known boundary.
        """
        bar = Bar.model_validate(bar.model_dump())
        opening = self._opens.get(bar.symbol)
        if (
            opening is None
            or not bar.is_complete_interval
            or (bar.open_time, bar.open, bar.snapshot_id)
            != (opening.timestamp, opening.price, opening.snapshot_id)
            or bar.ingest_time <= self._closed.get(bar.symbol, -1)
            or bar.ingest_time < self._clock.get(bar.symbol, 0)
        ):
            raise ValueError("completed bar must match the unprocessed opening and advance clock")
        keys = [key for key, op in self._resting.items() if op.symbol == bar.symbol]
        fills = []
        for key in keys:
            order = self._orders[key]
            limit = order.request.price
            assert limit is not None
            through = bar.low < limit if order.request.side is Side.BUY else bar.high > limit
            if through and bar.volume > 0:
                fills.append(self._filled(order, limit, bar.ingest_time, "MAKER"))
        for key in keys:
            self._resting.pop(key)
        self._closed[bar.symbol] = bar.ingest_time
        self._clock[bar.symbol] = bar.ingest_time
        for changed, fill in fills:
            self._report(changed, fill)
        self.dispatch_reports()
