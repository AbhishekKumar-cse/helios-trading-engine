from decimal import Decimal as D
from decimal import localcontext

import pytest

from helios.common.types import BookView, ExecutionReport, Fill, Mode, OrderState, Side
from helios.sim.ledger import LedgerError, PnLLedger


def fill(identifier, side, quantity, price, fee="1", time=10, symbol="BTCUSDT"):
    return Fill(
        fill_id=str(identifier),
        order_id="order",
        symbol=symbol,
        side=side,
        quantity=D(quantity),
        price=D(price),
        fee=D(fee),
        fee_asset="USDT",
        timestamp=time,
        venue_id="fixture",
        liquidity="TAKER",
        mode=Mode.BACKTEST,
    )


def marks(time=10, price="110", symbol="BTCUSDT"):
    return {
        symbol: BookView(
            symbol=symbol,
            timestamp=time,
            sequence=0,
            best_bid=D(price),
            best_ask=D(price),
            stale=False,
        )
    }


def test_open_add_reduce_flat_and_flip_exact_cost_and_separate_fees():
    ledger = PnLLedger(D(1000), Mode.BACKTEST)
    ledger.book(fill(1, Side.BUY, "2", "100"))
    ledger.book(fill(2, Side.BUY, "1", "130"))
    assert ledger.position("BTCUSDT").average_entry_price == 110
    snap = ledger.snapshot(10, marks(price="120"))
    assert (snap.cash, snap.realized_pnl, snap.unrealized_pnl, snap.fees, snap.equity) == (
        668,
        0,
        30,
        2,
        1028,
    )
    ledger.book(fill(3, Side.SELL, "1", "120"))
    assert ledger.position("BTCUSDT").average_entry_price == 110
    assert ledger.snapshot(10, marks()).realized_pnl == 10
    ledger.book(fill(4, Side.SELL, "3", "90"))
    position = ledger.position("BTCUSDT")
    assert position.quantity == -1 and position.average_entry_price == 90
    snap = ledger.snapshot(10, marks(price="80"))
    assert snap.realized_pnl == -30 and snap.unrealized_pnl == 10 and snap.fees == 4
    assert snap.equity == 976
    ledger.book(fill(5, Side.BUY, "1", "80"))
    assert ledger.position("BTCUSDT").average_entry_price is None
    snap = ledger.snapshot(10, {})
    assert snap.realized_pnl == -20 and snap.unrealized_pnl == 0 and snap.equity == 975


def test_short_add_reduce_and_flip_to_long():
    ledger = PnLLedger(D(1000), Mode.REPLAY)
    for event in [
        fill(1, Side.SELL, "1", "100"),
        fill(2, Side.SELL, "1", "120"),
        fill(3, Side.BUY, "1", "90"),
        fill(4, Side.BUY, "2", "80"),
    ]:
        ledger.book(event.model_copy(update={"mode": Mode.REPLAY}))
    assert ledger.position("BTCUSDT").quantity == 1
    assert ledger.position("BTCUSDT").average_entry_price == 80
    snap = ledger.snapshot(10, marks(price="90"))
    assert snap.realized_pnl == 50 and snap.unrealized_pnl == 10 and snap.equity == 1056


def test_only_fills_book_and_duplicates_and_validation_are_atomic():
    ledger = PnLLedger(D(1000), Mode.BACKTEST)
    ack = ExecutionReport(
        order_id="order",
        client_order_id="client",
        sequence=0,
        timestamp=10,
        state=OrderState.ACCEPTED,
        filled_quantity=D(0),
        remaining_quantity=D(1),
    )
    assert ledger.on_report(ack) is False
    assert ledger.snapshot(10, {}).equity == 1000
    event = fill(1, Side.BUY, "1", "100")
    assert ledger.book(event) is True and ledger.book(event) is False
    prior = ledger.snapshot(10, marks())
    for invalid in [
        event.model_copy(update={"price": D(101)}),
        fill(2, Side.BUY, "1", "100", time=9),
        fill(3, Side.BUY, "1", "100").model_copy(update={"fee_asset": "BTC"}),
        fill(4, Side.BUY, "1", "100").model_copy(update={"mode": Mode.PAPER}),
    ]:
        with pytest.raises(LedgerError):
            ledger.book(invalid)
    assert ledger.snapshot(10, marks()) == prior


def test_marks_are_explicit_fresh_and_only_unrealized_changes():
    ledger = PnLLedger(D(1000), Mode.BACKTEST)
    ledger.book(fill(1, Side.BUY, "1", "100"))
    first = ledger.snapshot(10, marks())
    second = ledger.snapshot(11, marks(time=11, price="120"))
    assert second.unrealized_pnl - first.unrealized_pnl == 10
    assert (second.cash, second.realized_pnl, second.fees) == (
        first.cash,
        first.realized_pnl,
        first.fees,
    )
    for invalid in (
        {},
        marks(),
        {"BTCUSDT": marks(11)["BTCUSDT"].model_copy(update={"stale": True})},
    ):
        with pytest.raises(LedgerError):
            ledger.snapshot(11, invalid)


def test_fractional_average_retains_exact_basis_independent_of_decimal_context():
    ledger = PnLLedger(D(1000), Mode.BACKTEST)
    with localcontext() as context:
        context.prec = 6
        ledger.book(fill(1, Side.BUY, "2", "100", fee="0"))
        ledger.book(fill(2, Side.BUY, "1", "101", fee="0"))
        assert ledger.position("BTCUSDT").average_entry_price == D("100.333333333333333333")
        ledger.book(fill(3, Side.SELL, "3", "102", fee="0"))
        snap = ledger.snapshot(10, {})
    assert snap.realized_pnl == 5 and snap.cash == 1005


def test_paper_reports_book_exactly_once_after_execution():
    from test_paper_venue import market, opening

    from helios.sim.paper import BarPaperVenue

    ledger = PnLLedger(D(1000), Mode.BACKTEST)
    venue = BarPaperVenue(Mode.BACKTEST)
    venue.subscribe_reports(ledger.on_report)
    venue.submit(market())
    venue.dispatch_reports()
    assert ledger.snapshot(10, {}).cash == 1000
    venue.on_open(opening(11))
    snap = ledger.snapshot(11, marks(11, "100"))
    assert snap.cash == D("969.963994")
    assert snap.unrealized_pnl == D("-.006") and snap.fees == D(".030006")
