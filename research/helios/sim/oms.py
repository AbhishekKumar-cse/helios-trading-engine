"""Session-scoped reference OMS identity and idempotent creation (133).

Only risk-authorized simulated requests enter this book. No venue submission,
fill, durable order storage or restart reconciliation is implied by creation.
"""

import re
from collections.abc import Callable
from decimal import Decimal
from threading import RLock
from uuid import uuid4

from helios.common.config import canonical_json
from helios.common.interfaces import RiskEngine
from helios.common.types import AuthorisedOrder, Mode, NewOrder, Order, OrderState


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
