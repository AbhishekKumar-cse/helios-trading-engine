"""Session-scoped reference OMS identity and idempotent creation (133).

Only risk-authorized simulated requests enter this book. No venue submission,
fill, durable order storage or restart reconciliation is implied by creation.
"""

import re
from collections.abc import Callable
from decimal import Decimal, localcontext
from threading import RLock
from uuid import uuid4

from helios.common.config import canonical_json
from helios.common.interfaces import RiskEngine
from helios.common.types import AuthorisedOrder, ExecutionReport, Mode, NewOrder, Order, OrderState

REPORT_TRANSITIONS = {
    OrderState.PENDING_NEW: frozenset((OrderState.ACCEPTED, OrderState.REJECTED)),
    OrderState.ACCEPTED: frozenset(
        (OrderState.PARTIALLY_FILLED, OrderState.FILLED, OrderState.CANCELLED, OrderState.EXPIRED)
    ),
    OrderState.PARTIALLY_FILLED: frozenset(
        (OrderState.PARTIALLY_FILLED, OrderState.FILLED, OrderState.CANCELLED, OrderState.EXPIRED)
    ),
    OrderState.PENDING_CANCEL: frozenset(
        (OrderState.ACCEPTED, OrderState.PARTIALLY_FILLED, OrderState.FILLED, OrderState.CANCELLED)
    ),
}


class OMSError(ValueError):
    pass


class OrderManagementSystem:
    def __init__(
        self, scope: str, mode: Mode, risk: RiskEngine, id_factory: Callable[[], str] | None = None
    ) -> None:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", scope):
            raise OMSError("OMS requires a readable session scope")
        self.scope, self.mode, self.risk = scope, Mode(mode), risk
        self._id_factory = id_factory if id_factory is not None else lambda: uuid4().hex
        self._orders: dict[str, Order] = {}
        self._clients: dict[str, tuple[str, str]] = {}
        self._reports: dict[str, dict[int, str]] = {}
        self._fill_ids: set[str] = set()
        self._lock = RLock()

    def submit(self, authorised: AuthorisedOrder) -> Order:
        authorised = AuthorisedOrder.model_validate(authorised.model_dump())
        action = authorised.action
        if not isinstance(action, NewOrder) or action.mode != self.mode:
            raise OMSError("OMS creation requires a NEW request in this simulated mode")
        fingerprint = canonical_json(action)
        with self._lock:
            prior = self._clients.get(action.client_order_id)
            if prior is not None:
                if prior[0] != fingerprint:
                    raise OMSError("client_order_id reused with a different request")
                return self._orders[prior[1]]
            decision = self.risk.check(action)  # older authorization cannot bypass a new kill trip
            if (
                not decision.accepted
                or decision.authorised is None
                or decision.authorised.action != action
                or decision.authorised.limits_hash != authorised.limits_hash
            ):
                raise OMSError("fresh risk authorization required for creation")
            suffix = self._id_factory()
            if not isinstance(suffix, str) or not suffix:
                raise OMSError("order ID generator returned an invalid identifier")
            order_id = f"{self.mode.value.lower()}_{self.scope}_{suffix}"
            if order_id in self._orders:
                raise OMSError("order ID collision")
            order = Order(
                order_id=order_id,
                request=action,
                state=OrderState.CREATED,
                filled_quantity=Decimal(0),
                remaining_quantity=action.quantity,
                timestamp=decision.timestamp,
            )
            self._orders[order_id] = order
            self._clients[action.client_order_id] = (fingerprint, order_id)
            return order

    def get(self, order_id: str) -> Order:
        with self._lock:
            try:
                return self._orders[order_id]
            except KeyError as exc:
                raise OMSError("unknown order") from exc

    def snapshot(self) -> tuple[Order, ...]:
        with self._lock:
            return tuple(self._orders[key] for key in sorted(self._orders))

    def _local_transition(self, order_id: str, state: OrderState, timestamp: int) -> Order:
        with self._lock:
            old = self.get(order_id)
            allowed = (state is OrderState.PENDING_NEW and old.state is OrderState.CREATED) or (
                state is OrderState.PENDING_CANCEL
                and old.state in (OrderState.ACCEPTED, OrderState.PARTIALLY_FILLED)
            )
            if not allowed or timestamp < old.timestamp:
                raise OMSError("illegal local transition or backwards clock")
            changed = Order.model_validate(
                old.model_dump() | dict(state=state, timestamp=timestamp)
            )
            self._orders[order_id] = changed
            return changed

    def mark_pending(self, order_id: str, timestamp: int) -> Order:
        return self._local_transition(order_id, OrderState.PENDING_NEW, timestamp)

    def request_cancel(self, order_id: str, timestamp: int) -> Order:
        return self._local_transition(order_id, OrderState.PENDING_CANCEL, timestamp)

    def on_report(self, report: ExecutionReport) -> Order:
        """Apply ordered external evidence atomically; ACK is never a fill.

        Duplicate known reports are lookups. Missing sequences, conflicting
        duplicates, reused fill IDs and invalid quantities never modify the book.
        """
        report = ExecutionReport.model_validate(report.model_dump())
        with self._lock:
            old = self.get(report.order_id)
            if report.client_order_id != old.request.client_order_id:
                raise OMSError("report client identity mismatch")
            fingerprint = canonical_json(report)
            history = self._reports.get(report.order_id, {})
            if report.sequence in history:
                if history[report.sequence] != fingerprint:
                    raise OMSError("conflicting duplicate report")
                return old
            if history and report.sequence != max(history) + 1:
                raise OMSError("out-of-order or missing report sequence; reconcile first")
            if report.timestamp < old.timestamp or report.state not in REPORT_TRANSITIONS.get(
                old.state, frozenset()
            ):
                raise OMSError("illegal report transition or backwards clock")
            with localcontext() as context:
                context.prec = 80
                delta = report.filled_quantity - old.filled_quantity
                if delta < 0 or report.filled_quantity > old.request.quantity:
                    raise OMSError("cumulative fill regressed or exceeded quantity")
                if old.request.quantity - report.filled_quantity != report.remaining_quantity:
                    raise OMSError("report violates quantity conservation")
            fill = report.fill
            if delta > 0:
                if (
                    fill is None
                    or fill.quantity != delta
                    or fill.fill_id in self._fill_ids
                    or fill.symbol != old.request.symbol
                    or fill.side != old.request.side
                    or fill.mode != self.mode
                    or fill.timestamp < old.request.timestamp
                    or fill.timestamp > report.timestamp
                ):
                    raise OMSError("new cumulative quantity requires matching unique fill evidence")
            elif fill is not None:
                raise OMSError("fill evidence requires an increase in cumulative quantity")
            changed = Order(
                order_id=old.order_id,
                request=old.request,
                state=report.state,
                filled_quantity=report.filled_quantity,
                remaining_quantity=report.remaining_quantity,
                timestamp=report.timestamp,
            )
            self._orders[old.order_id] = changed
            self._reports.setdefault(old.order_id, {})[report.sequence] = fingerprint
            if fill is not None:
                self._fill_ids.add(fill.fill_id)
            return changed
