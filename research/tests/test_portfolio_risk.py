from decimal import Decimal as D

import pytest
from test_common_types import lineage, request

from helios.common.types import (
    AmendOrder,
    Mode,
    Order,
    OrderState,
    Position,
    ReasonCode,
    RiskState,
    Side,
)
from helios.sim.portfolio_risk import (
    PortfolioLimits,
    PortfolioRisk,
    PortfolioSnapshot,
    PositionLimits,
)
from helios.sim.price_risk import PriceObservation


def working(quantity="1.5", side=Side.BUY, **changes):
    return Order(
        **(
            dict(
                order_id="pending",
                request=request(quantity=D(quantity), side=side),
                state=OrderState.ACCEPTED,
                filled_quantity=D(0),
                remaining_quantity=D(quantity),
                timestamp=10,
            )
            | changes
        )
    )


def risk(current="18", orders=None, gross="5000", view_changes=None):
    limits = PortfolioLimits(
        instruments=tuple(
            PositionLimits(
                symbol=s,
                max_order_notional=D(5000),
                price_band_fraction=D(".5"),
                median_window=1,
                max_price_age_us=0,
                max_position_notional=D(2000),
            )
            for s in ("BTCUSDT", "ETHUSDT")
        ),
        max_gross_exposure=D(gross),
    )
    marks = tuple(
        PriceObservation(symbol=s, timestamp=10, price=D(100), snapshot_id="snapshot")
        for s in ("BTCUSDT", "ETHUSDT")
    )
    positions = (
        Position(
            symbol="BTCUSDT",
            quantity=D(current),
            average_entry_price=D(100) if D(current) else None,
            timestamp=10,
        ),
    )
    view = PortfolioSnapshot(
        **(
            dict(
                timestamp=10,
                snapshot_id="snapshot",
                positions=positions,
                open_orders=(working(),) if orders is None else orders,
                marks=marks,
            )
            | (view_changes or {})
        )
    )
    engine = PortfolioRisk(
        limits, lambda: None, lambda s: tuple(m for m in marks if m.symbol == s), lambda: view
    )
    engine.state = lambda: RiskState(
        timestamp=10, halted=False, daily_pnl=D(0), limits_hash=engine.limits_hash
    )
    return engine


def test_1800_plus_150_plus_200_rejects_and_boundary_passes():
    assert risk().check(request(quantity=D(2))).reason is ReasonCode.POSITION_LIMIT
    assert risk().check(request(quantity=D(".5"))).accepted


def test_opposing_orders_do_not_cancel_possible_fill_exposure():
    buy = working("3")
    sell = working("3", Side.SELL).model_copy(update={"order_id": "sell"})
    assert (
        risk(orders=(buy, sell)).check(request(quantity=D(".1"))).reason
        is ReasonCode.POSITION_LIMIT
    )
    pending = working().model_copy(update={"state": OrderState.PENDING_CANCEL})
    assert risk(orders=(pending,)).check(request(quantity=D(2))).reason is ReasonCode.POSITION_LIMIT


def test_cross_coin_gross_exposure_uses_absolute_positions():
    other = Position(symbol="ETHUSDT", quantity=D(-10), average_entry_price=D(100), timestamp=10)
    current = Position(symbol="BTCUSDT", quantity=D(10), average_entry_price=D(100), timestamp=10)
    engine = risk(
        current="10", orders=(), gross="2100", view_changes={"positions": (current, other)}
    )
    assert engine.check(request(quantity=D(2))).reason is ReasonCode.EXPOSURE_LIMIT


def test_amend_replaces_old_remaining_without_double_counting():
    order = working(
        "3",
        request=request(quantity=D(4)),
        state=OrderState.PARTIALLY_FILLED,
        filled_quantity=D(1),
        remaining_quantity=D(3),
    )
    engine = risk(current="16", orders=(order,))
    amend = AmendOrder(
        request_id="amend",
        order_id="pending",
        symbol="BTCUSDT",
        quantity=D(5),
        price=D(100),
        timestamp=10,
        lineage=lineage(),
        mode=Mode.BACKTEST,
    )
    assert engine.check(amend).accepted
    assert (
        engine.check(amend.model_copy(update={"quantity": D(6)})).reason
        is ReasonCode.POSITION_LIMIT
    )
    assert (
        engine.check(amend.model_copy(update={"order_id": "unknown"})).reason
        is ReasonCode.VENUE_REJECTED
    )


@pytest.mark.parametrize("change", [{"timestamp": 11}, {"snapshot_id": "other"}, {"marks": ()}])
def test_inconsistent_or_missing_portfolio_fails_closed(change):
    decision = risk(view_changes=change).check(request())
    assert decision.reason is ReasonCode.STALE_MARKET_DATA and not decision.accepted
