from decimal import Decimal as D

import pytest
from test_bar_strategy import alpha
from test_common_types import request

from helios.common.interfaces import Strategy
from helios.common.types import AlphaStatus, BookView, Order, OrderState, Position, RiskState, Side
from helios.sim.strategy import BarStrategy, BarStrategyConfig


def context():
    return (
        BookView(
            symbol="BTCUSDT",
            timestamp=10,
            sequence=1,
            best_bid=D(100),
            best_ask=D(100),
            stale=False,
        ),
        Position(symbol="BTCUSDT", quantity=D(0), average_entry_price=None, timestamp=10),
        RiskState(timestamp=10, halted=False, daily_pnl=D(0), limits_hash="b" * 64),
    )


def strategy(threshold="0.01"):
    return BarStrategy(
        BarStrategyConfig(
            strategy_id="test",
            capital=D(10000),
            max_weight=D("0.2"),
            rebalance_threshold=D(threshold),
        )
    )


def test_threshold_boundary_and_idempotent_market_intent():
    book, pos, risk = context()
    typed: Strategy = strategy()
    assert typed.on_update(alpha(0.049), book, pos, (), risk) == []
    orders = typed.on_update(alpha(0.05), book, pos, (), risk)
    assert orders[0].quantity == D(1) and orders[0].side is Side.BUY
    assert orders == typed.on_update(alpha(0.05), book, pos, (), risk)
    assert orders[0].lineage == alpha().lineage and orders[0].timestamp == 10


def test_projected_remaining_orders_prevent_duplicate_exposure():
    book, pos, risk = context()
    working = Order(
        order_id="working",
        request=request(quantity=D(10)),
        state=OrderState.PARTIALLY_FILLED,
        filled_quantity=D(4),
        remaining_quantity=D(6),
        timestamp=10,
    )
    pos = Position(symbol="BTCUSDT", quantity=D(4), average_entry_price=D(100), timestamp=10)
    assert strategy().on_update(alpha(0.5), book, pos, (working,), risk) == []
    sell = strategy().on_update(alpha(-0.5), book, pos, (working,), risk)[0]
    assert sell.side is Side.SELL and sell.quantity == D(20)
    cancelling = working.model_copy(update={"state": OrderState.PENDING_CANCEL})
    assert strategy().on_update(alpha(0.5), book, pos, (cancelling,), risk) == []


@pytest.mark.parametrize("field", ["halted", "stale", "limits", "future", "unavailable"])
def test_ineligible_state_cannot_create_orders(field):
    book, pos, risk = context()
    signal = alpha()
    if field == "halted":
        risk = risk.model_copy(update={"halted": True})
    if field == "stale":
        book = book.model_copy(update={"stale": True})
    if field == "limits":
        risk = risk.model_copy(update={"limits_hash": None})
    if field == "future":
        book = book.model_copy(update={"timestamp": 11})
    if field == "unavailable":
        signal = alpha(None, status=AlphaStatus.UNAVAILABLE)
    assert strategy().on_update(signal, book, pos, (), risk) == []


def test_symbol_mismatch_and_duplicate_working_orders_refused():
    book, pos, risk = context()
    with pytest.raises(ValueError, match="symbols"):
        strategy().on_update(alpha(), book.model_copy(update={"symbol": "ETHUSDT"}), pos, (), risk)
    working = Order(
        order_id="same",
        request=request(quantity=D(10)),
        state=OrderState.ACCEPTED,
        filled_quantity=D(0),
        remaining_quantity=D(10),
        timestamp=10,
    )
    with pytest.raises(ValueError, match="duplicate"):
        strategy().on_update(alpha(), book, pos, (working, working), risk)
