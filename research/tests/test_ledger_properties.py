import logging
from decimal import Decimal as D
from decimal import localcontext
from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from test_ledger import fill, marks

from helios.common.types import Mode, Side
from helios.sim.ledger import PnLLedger, ReconciliationError

events = st.lists(
    st.tuples(
        st.sampled_from(["BTCUSDT", "ETHUSDT"]),
        st.sampled_from([Side.BUY, Side.SELL]),
        st.integers(1, 10000),
        st.sampled_from([0, 6, 18]),
        st.integers(1, 100000),
        st.integers(0, 100),
        st.integers(1, 100000),
    ),
    min_size=1,
    max_size=80,
)


@given(events)
@settings(max_examples=150, deadline=None)
def test_every_snapshot_reconciles_to_independent_cash_and_inventory_model(sequence):
    ledger = PnLLedger(D(1000000), Mode.BACKTEST)
    cash = Fraction(1000000)
    positions = {"BTCUSDT": Fraction(0), "ETHUSDT": Fraction(0)}
    fees = Fraction(0)
    for index, (symbol, side, units, places, ticks, fee_units, mark_ticks) in enumerate(sequence):
        # Construct exact input decimals without dependence on ambient precision.
        quantity = D(f"{units}e-{places}")
        price, fee, mark = D(f"{ticks}e-2"), D(f"{fee_units}e-6"), D(f"{mark_ticks}e-2")
        event = fill(
            index, side, str(quantity), str(price), str(fee), time=index + 1, symbol=symbol
        )
        signed = Fraction(quantity) * (1 if side is Side.BUY else -1)
        cash -= signed * Fraction(price) + Fraction(fee)
        positions[symbol] += signed
        fees += Fraction(fee)
        with localcontext() as context:
            context.prec = 7
            assert ledger.book(event)
            assert not ledger.book(event)
            books = {s: marks(index + 1, str(mark), s)[s] for s in positions}
            snap = ledger.snapshot(index + 1, books)
        expected_equity = cash + sum(q * Fraction(mark) for q in positions.values())
        assert abs(Fraction(snap.cash) - cash) <= Fraction(1, 2 * 10**18)
        assert abs(Fraction(snap.equity) - expected_equity) <= Fraction(1, 2 * 10**18)
        assert Fraction(snap.fees) == fees
        assert abs(
            Fraction(snap.equity)
            - (1000000 + Fraction(snap.realized_pnl) + Fraction(snap.unrealized_pnl) - fees)
        ) <= Fraction(2, 10**18)
        for s, quantity_model in positions.items():
            assert Fraction(ledger.position(s).quantity) == quantity_model


@pytest.mark.parametrize("field", ["_cash", "_realized", "_fees"])
def test_reconciliation_break_logs_critical_and_latches_reporting_halt(field, caplog):
    ledger = PnLLedger(D(1000), Mode.BACKTEST)
    ledger.book(fill(1, Side.BUY, "1", "100"))
    old = getattr(ledger, field)
    setattr(ledger, field, old + 1)
    with caplog.at_level(logging.CRITICAL), pytest.raises(ReconciliationError):
        ledger.snapshot(10, marks())
    assert "LEDGER_RECONCILIATION_BREAK" in caplog.text
    setattr(ledger, field, old)
    with pytest.raises(ReconciliationError, match="halted"):
        ledger.snapshot(10, marks())
    with pytest.raises(ReconciliationError, match="halted"):
        ledger.book(fill(2, Side.SELL, "1", "100"))
