from decimal import Decimal as D

import pytest
from test_common_types import lineage, request

from helios.common.interfaces import RiskEngine
from helios.common.types import AmendOrder, CancelOrder, Mode, OrderType, ReasonCode, RiskState
from helios.sim.price_risk import (
    InstrumentOrderLimits,
    PriceObservation,
    SizePriceLimits,
    SizePriceRisk,
)


def engine(history=None, **state_changes):
    config = SizePriceLimits(
        instruments=(
            InstrumentOrderLimits(
                symbol="BTCUSDT",
                max_order_notional=D(1000),
                price_band_fraction=D(".1"),
                median_window=3,
                max_price_age_us=2,
            ),
        )
    )
    state = RiskState(
        **(
            dict(
                timestamp=10,
                halted=False,
                daily_pnl=D(0),
                limits_hash=SizePriceRisk(config, lambda: None, lambda _: ()).limits_hash,
            )
            | state_changes
        )
    )
    prices = (
        tuple(
            PriceObservation(symbol="BTCUSDT", timestamp=t, price=D(p), snapshot_id="snapshot")
            for t, p in ((8, 100), (9, 100), (10, 100))
        )
        if history is None
        else history
    )
    return SizePriceRisk(config, lambda: state, lambda _: prices)


@pytest.mark.parametrize(
    "price,accepted", [("90", True), ("110", True), ("89.99", False), ("110.01", False)]
)
def test_inclusive_median_band(price, accepted):
    typed: RiskEngine = engine()
    result = typed.check(request(price=D(price)))
    assert result.accepted is accepted
    assert result.reason is (ReasonCode.ACCEPTED if accepted else ReasonCode.PRICE_BAND)


def test_order_size_boundary_and_first_failure():
    assert engine().check(request(quantity=D(10))).accepted
    assert engine().check(request(quantity=D("10.01"))).reason is ReasonCode.MAX_ORDER_SIZE
    assert engine().check(request(quantity=D(10), price=D(150))).reason is ReasonCode.MAX_ORDER_SIZE


@pytest.mark.parametrize(
    "problem", ["future", "stale", "missing", "duplicate", "snapshot", "backwards"]
)
def test_bad_price_history_rejects_without_authorization(problem):
    history = [
        PriceObservation(symbol="BTCUSDT", timestamp=t, price=D(100), snapshot_id="snapshot")
        for t in (8, 9, 10)
    ]
    if problem == "future":
        history[-1] = history[-1].model_copy(update={"timestamp": 11})
    if problem == "stale":
        history = [p.model_copy(update={"timestamp": p.timestamp - 4}) for p in history]
    if problem == "missing":
        history.pop()
    if problem == "duplicate":
        history[-1] = history[1]
    if problem == "snapshot":
        history[-1] = history[-1].model_copy(update={"snapshot_id": "other"})
    if problem == "backwards":
        history.reverse()
    decision = engine(tuple(history)).check(request())
    assert decision.reason is ReasonCode.STALE_MARKET_DATA and decision.authorised is None


def test_market_spike_and_amend_total_quantity():
    history = tuple(
        PriceObservation(symbol="BTCUSDT", timestamp=t, price=D(p), snapshot_id="snapshot")
        for t, p in ((8, 100), (9, 100), (10, 125))
    )
    assert (
        engine(history).check(request(order_type=OrderType.MARKET, price=None)).reason
        is ReasonCode.PRICE_BAND
    )
    amend = AmendOrder(
        request_id="amend",
        order_id="order",
        symbol="BTCUSDT",
        quantity=D(11),
        price=D(100),
        timestamp=10,
        lineage=lineage(),
        mode=Mode.BACKTEST,
    )
    assert engine().check(amend).reason is ReasonCode.MAX_ORDER_SIZE


def test_unknown_instrument_and_mismatched_limit_hash():
    assert engine().check(request(symbol="ETHUSDT")).reason is ReasonCode.UNKNOWN_INSTRUMENT
    assert engine(limits_hash="b" * 64).check(request()).reason is ReasonCode.MISSING_LIMITS


def test_cancel_requires_binding_but_no_prices_and_provider_error_fails_closed():
    risk = engine()

    def fail(symbol):
        raise RuntimeError("provider failed")

    risk.prices = fail
    cancel = CancelOrder(
        request_id="cancel",
        order_id="order",
        symbol="BTCUSDT",
        timestamp=10,
        lineage=lineage(),
        mode=Mode.BACKTEST,
    )
    assert risk.check(cancel).accepted
    assert risk.check(request()).reason is ReasonCode.INTERNAL_ERROR


def test_one_reference_read_for_both_checks_and_exact_authorization():
    risk = engine()
    provider = risk.prices
    calls = []

    def prices(symbol):
        calls.append(symbol)
        return provider(symbol)

    risk.prices = prices
    action = request()
    result = risk.check(action)
    assert calls == ["BTCUSDT"] and result.authorised.action == action
    assert result.authorised.limits_hash == risk.limits_hash
