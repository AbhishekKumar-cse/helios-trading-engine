"""Explicit NSE intraday charge diagnostic; never silently replaces frozen costs.

Exchange/IPFT rates are dated; brokerage is a current public Zerodha scenario,
not proof of a historical account tariff. Only same-day flat cash equity is
supported. Contract-note reconciliation and execution slippage remain separate.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, localcontext
from typing import Literal

ZERO = Decimal(0)
PAISE = Decimal("0.01")
CRORE = Decimal("10000000")


@dataclass(frozen=True)
class ChargeTrade:
    day: date
    symbol: str
    order_id: str
    side: Literal["BUY", "SELL"]
    quantity: Decimal
    price: Decimal

    def __post_init__(self) -> None:
        if (
            type(self.day) is not date
            or not date(2025, 1, 1) <= self.day <= date(2026, 6, 30)
            or not self.symbol
            or not self.order_id
            or self.side not in ("BUY", "SELL")
            or not isinstance(self.quantity, Decimal)
            or not isinstance(self.price, Decimal)
            or not self.quantity.is_finite()
            or not self.price.is_finite()
            or self.quantity <= 0
            or self.price <= 0
            or self.quantity != self.quantity.to_integral_value()
        ):
            raise ValueError("requires whole-share, dated, finite cash-equity execution")


@dataclass(frozen=True)
class ChargeEstimate:
    brokerage: Decimal
    exchange: Decimal
    ipft: Decimal
    sebi: Decimal
    gst: Decimal
    stamp: Decimal
    stt: Decimal
    turnover: Decimal
    orders: int

    @property
    def total(self) -> Decimal:
        with localcontext() as context:
            context.prec = 100
            return sum(
                (
                    self.brokerage,
                    self.exchange,
                    self.ipft,
                    self.sebi,
                    self.gst,
                    self.stamp,
                    self.stt,
                ),
                ZERO,
            )


def estimate_intraday_charges(trades: Sequence[ChargeTrade]) -> ChargeEstimate:
    """One client, no overnight inventory; order cap applies across partial fills.

    STT uses rounded daily security VWAP, per-security paise rounding, then
    client-day nearest rupee (NSE CMTR5588 methodology, current cash rate).
    Other components remain unrounded estimates, not invented invoice precision.
    """
    orders: dict[tuple[date, str], tuple[str, str, Decimal]] = {}
    securities: dict[tuple[date, str], list[Decimal]] = defaultdict(lambda: [ZERO] * 4)
    exchange = ipft = sebi = stamp = turnover = ZERO
    with localcontext() as context:
        context.prec = 100
        for trade in trades:
            value = trade.quantity * trade.price
            key = (trade.day, trade.order_id)
            prior = orders.get(key)
            if prior is not None and prior[:2] != (trade.symbol, trade.side):
                raise ValueError("one executed order cannot change symbol or side")
            orders[key] = (trade.symbol, trade.side, value + (prior[2] if prior else ZERO))
            row = securities[(trade.day, trade.symbol)]
            index = 0 if trade.side == "BUY" else 2
            row[index] += trade.quantity
            row[index + 1] += value
            tx, fund = (
                (Decimal("297"), Decimal("10"))
                if trade.day < date(2026, 3, 1)
                else (Decimal("306.99"), Decimal("0.01"))
            )
            exchange += value * tx / CRORE
            ipft += value * fund / CRORE
            sebi += value * Decimal("10") / CRORE
            if trade.side == "BUY":
                stamp += value * Decimal("0.00003")
            turnover += value
        brokerage = sum(
            (min(value * Decimal("0.0003"), Decimal("20")) for _, _, value in orders.values()), ZERO
        )
        daily_stt: dict[date, Decimal] = defaultdict(lambda: ZERO)
        for (day, _), (buy_qty, buy_value, sell_qty, sell_value) in securities.items():
            if buy_qty != sell_qty:
                raise ValueError("intraday diagnostic refuses non-flat security/day quantities")
            vwap = ((buy_value + sell_value) / (buy_qty + sell_qty)).quantize(
                PAISE, rounding=ROUND_HALF_UP
            )
            daily_stt[day] += (sell_qty * vwap * Decimal("0.00025")).quantize(
                PAISE, rounding=ROUND_HALF_UP
            )
        stt = sum(
            (value.quantize(Decimal(1), rounding=ROUND_HALF_UP) for value in daily_stt.values()),
            ZERO,
        )
        gst = (brokerage + exchange + ipft + sebi) * Decimal("0.18")
        return ChargeEstimate(
            brokerage, exchange, ipft, sebi, gst, stamp, stt, turnover, len(orders)
        )


class IntradayChargeBook:
    """Causal per-fill fees; a signed end-of-day adjustment settles exact-day STT.

    One client/day accounting scope, including every security in that scope.
    Brokerage remains a scenario; rounding is not contract-note certification.
    """

    def __init__(self, multiplier: Decimal = Decimal(1)) -> None:
        if not multiplier.is_finite() or multiplier < 1:
            raise ValueError("charge stress must be finite and at least one")
        self.multiplier = multiplier
        self.trades: list[ChargeTrade] = []
        self.orders: dict[str, tuple[str, str, Decimal]] = {}
        self.paid = ZERO
        self.settled = False

    def record(self, trade: ChargeTrade) -> Decimal:
        if self.settled or (self.trades and trade.day != self.trades[0].day):
            raise ValueError("charge book requires one unsettled client day")
        prior = self.orders.get(trade.order_id)
        if prior is not None and prior[:2] != (trade.symbol, trade.side):
            raise ValueError("executed order identity changed")
        with localcontext() as context:
            context.prec = 100
            value = trade.quantity * trade.price
            previous = prior[2] if prior else ZERO
            brokerage = min((previous + value) * Decimal(".0003"), Decimal(20))
            brokerage -= min(previous * Decimal(".0003"), Decimal(20))
            # Exchange + IPFT total 307/crore on both sides in both dated regimes.
            taxable = brokerage + value * Decimal(317) / CRORE
            fee = taxable * Decimal("1.18")
            fee += value * (Decimal(".00003") if trade.side == "BUY" else Decimal(".00025"))
            amount = (fee * self.multiplier).quantize(Decimal("1e-18"), rounding=ROUND_HALF_EVEN)
            self.orders[trade.order_id] = (trade.symbol, trade.side, previous + value)
            self.trades.append(trade)
            self.paid += amount
            return amount

    def settle(self) -> tuple[ChargeEstimate, Decimal]:
        if self.settled:
            raise ValueError("charge book already settled")
        estimate = estimate_intraday_charges(self.trades)  # Refuses non-flat inventory.
        with localcontext() as context:
            context.prec = 100
            adjustment = (estimate.total * self.multiplier).quantize(
                Decimal("1e-18"), rounding=ROUND_HALF_EVEN
            ) - self.paid
        self.settled = True
        return estimate, adjustment
