"""Fill-only average-cost accounting with explicit, contemporaneous mid marks (143)."""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, localcontext
from fractions import Fraction
from typing import Literal

from pydantic import TypeAdapter

from helios.common.config import HeliosConfig, config_hash
from helios.common.types import (
    BookView,
    ExecutionReport,
    Fill,
    Mode,
    Money,
    PnLSnapshot,
    Position,
    Side,
    Timestamp,
)
from helios.sim.paper import rounded

LOGGER = logging.getLogger(__name__)


class LedgerError(ValueError):
    pass


class LedgerConfig(HeliosConfig):
    initial_cash: Money
    mode: Mode
    quote_asset: Literal["USDT"] = "USDT"
    mark: Literal["contemporaneous_book_mid"] = "contemporaneous_book_mid"
    accounting: Literal["exact_average_cost_v1"] = "exact_average_cost_v1"
    rounding: Literal["half_even_18_decimals"] = "half_even_18_decimals"


def decimal_value(value: Fraction) -> Decimal:
    with localcontext() as context:
        context.prec = 120
        return rounded(Decimal(value.numerator) / Decimal(value.denominator))


@dataclass(frozen=True)
class _Lot:
    quantity: Fraction = Fraction(0)
    basis: Fraction = Fraction(0)  # positive absolute inventory cost
    timestamp: int = 0


class PnLLedger:
    """One simulated accounting scope; retries are idempotent, conflicts fail closed.

    Fractions retain exact weighted average costs internally. Only public numeric
    records round half-even to 18 decimals; caller Decimal precision has no effect.
    """

    def __init__(self, initial_cash: Decimal, mode: Mode, quote_asset: str = "USDT") -> None:
        initial_cash = TypeAdapter(Money).validate_python(initial_cash)
        if initial_cash <= 0 or quote_asset != "USDT":
            raise LedgerError("positive initial cash and USDT quote are required")
        self.mode, self.quote_asset = Mode(mode), quote_asset
        self._initial = Fraction(initial_cash)
        self._cash = self._initial
        self._realized = Fraction(0)
        self._fees = Fraction(0)
        self._lots: dict[str, _Lot] = {}
        self._fills: dict[str, Fill] = {}
        self._clock = 0
        self.config_hash = config_hash(LedgerConfig(initial_cash=initial_cash, mode=self.mode))

    def position(self, symbol: str) -> Position:
        lot = self._lots.get(symbol, _Lot())
        return Position(
            symbol=symbol,
            quantity=decimal_value(lot.quantity),
            timestamp=lot.timestamp,
            average_entry_price=(
                None if lot.quantity == 0 else decimal_value(lot.basis / abs(lot.quantity))
            ),
        )

    def on_report(self, report: ExecutionReport) -> bool:
        report = ExecutionReport.model_validate(report.model_dump())
        return False if report.fill is None else self.book(report.fill)

    def book(self, fill: Fill) -> bool:
        fill = Fill.model_validate(fill.model_dump())
        prior = self._fills.get(fill.fill_id)
        if prior is not None:
            if prior != fill:
                raise LedgerError("conflicting duplicate fill")
            return False
        if (
            fill.mode != self.mode
            or fill.fee_asset != self.quote_asset
            or not fill.symbol.endswith(self.quote_asset)
            or fill.symbol == self.quote_asset
            or fill.timestamp < self._clock
        ):
            raise LedgerError("fill mode, quote currency or chronological clock mismatch")
        lot = self._lots.get(fill.symbol, _Lot())
        quantity, price, fee = Fraction(fill.quantity), Fraction(fill.price), Fraction(fill.fee)
        signed = quantity if fill.side is Side.BUY else -quantity
        new_quantity = lot.quantity + signed
        realized = self._realized
        if lot.quantity == 0 or (lot.quantity > 0) == (signed > 0):
            basis = lot.basis + price * quantity
        else:
            average = lot.basis / abs(lot.quantity)
            closed = min(abs(lot.quantity), quantity)
            direction = 1 if lot.quantity > 0 else -1
            realized += closed * (price - average) * direction
            if new_quantity == 0:
                basis = Fraction(0)
            elif (new_quantity > 0) == (lot.quantity > 0):
                basis = average * abs(new_quantity)
            else:
                basis = price * abs(new_quantity)
        cash = self._cash - signed * price - fee
        new_lot = _Lot(new_quantity, basis, fill.timestamp)
        # Validate all public numeric ranges before changing authoritative state.
        Position(
            symbol=fill.symbol,
            quantity=decimal_value(new_quantity),
            timestamp=fill.timestamp,
            average_entry_price=None
            if new_quantity == 0
            else decimal_value(basis / abs(new_quantity)),
        )
        for amount in (cash, realized, self._fees + fee):
            TypeAdapter(Money).validate_python(decimal_value(amount))
        self._lots[fill.symbol] = new_lot
        self._cash, self._realized, self._fees = cash, realized, self._fees + fee
        self._clock = fill.timestamp
        self._fills[fill.fill_id] = fill
        return True

    def snapshot(self, timestamp: int, marks: Mapping[str, BookView]) -> PnLSnapshot:
        timestamp = TypeAdapter(Timestamp).validate_python(timestamp)
        if timestamp < self._clock:
            raise LedgerError("snapshot clock cannot regress")
        market_value = unrealized = Fraction(0)
        for symbol, lot in self._lots.items():
            if lot.quantity == 0:
                continue
            if symbol not in marks:
                raise LedgerError("every nonflat position requires a current midpoint mark")
            book = BookView.model_validate(marks[symbol].model_dump())
            if (
                book.symbol != symbol
                or book.timestamp != timestamp
                or book.stale
                or book.best_bid is None
                or book.best_ask is None
            ):
                raise LedgerError(
                    "midpoint requires fresh matching two-sided book at snapshot time"
                )
            mark = (Fraction(book.best_bid) + Fraction(book.best_ask)) / 2
            market_value += lot.quantity * mark
            direction = 1 if lot.quantity > 0 else -1
            unrealized += lot.quantity * mark - direction * lot.basis
        result = PnLSnapshot(
            timestamp=timestamp,
            quote_asset=self.quote_asset,
            cash=decimal_value(self._cash),
            equity=decimal_value(self._cash + market_value),
            realized_pnl=decimal_value(self._realized),
            unrealized_pnl=decimal_value(unrealized),
            fees=decimal_value(self._fees),
            mode=self.mode,
            config_hash=self.config_hash,
        )
        self._clock = timestamp
        return result
