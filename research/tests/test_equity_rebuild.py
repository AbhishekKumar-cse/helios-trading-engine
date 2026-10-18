"""Causal source controls and hand-checked execution/accounting regressions."""

import json
from datetime import date
from decimal import Decimal as D

import pandas as pd
import pytest

from helios.alpha.evaluator import AlphaSeries
from helios.alpha.output import bound_alpha
from helios.backtest.equity import replay_session
from helios.common.types import Mode
from helios.equities.charges import ChargeTrade, IntradayChargeBook, estimate_intraday_charges
from helios.equities.config import EquityResearchPolicy
from helios.equities.features import minute_samples
from helios.equities.rebuild import membership, parse_reviewed_candles, schedule, verify_price_day
from helios.sim.ledger import FeeAdjustment, LedgerError, PnLLedger


def reviewed_frame(day, minute=555, slots=375):
    stamps = pd.date_range(day, periods=slots, freq="min", tz="Asia/Kolkata")
    stamps += pd.Timedelta(minutes=minute)
    rows = [[stamp.isoformat(), 100, 101, 99, 100, 10000, 0] for stamp in stamps]
    return parse_reviewed_candles(
        json.dumps(dict(status="success", data=dict(candles=rows))).encode(),
        "EXAMPLE",
        day,
        day,
        {day: dict(open_minute=minute, slots=slots)},
    )


def policy(**overrides):
    return EquityResearchPolicy(
        version="nse_minute_research_v2",
        interval="1m",
        session="reviewed_sessions_v2",
        commission_tax_proxy_bps=0,
        **overrides,
    )


def replay(frame, selected_policy):
    alpha = bound_alpha(
        AlphaSeries(
            "EXAMPLE",
            frame.open_time,
            pd.Series(1.0, index=frame.index),
            pd.Series(True, index=frame.index),
        )
    )
    return replay_session(
        frame,
        alpha,
        selected_policy,
        snapshot_id="a" * 64,
        alpha_id="nse_fixture_v2",
        code_commit="b" * 40,
    )


def test_membership_uses_effective_dates_and_preserves_unlisted_dummies():
    assert membership("BSE", "2026-06-30") == (False, False)
    assert membership("BPCL", "2025-03-27") == (True, True)
    assert membership("BPCL", "2025-03-28") == (False, False)
    assert membership("ETERNAL", "2025-03-27") == (False, False)
    assert membership("ETERNAL", "2025-03-28") == (True, True)
    assert membership("TMCV", "2025-10-14") == (True, False)
    assert membership("TMCV", "2025-11-12") == (True, True)
    assert membership("TMCV", "2025-11-17") == (False, False)
    assert membership("KWIL", "2026-02-23") == (True, True)
    assert membership("KWIL", "2026-02-24") == (False, False)
    with pytest.raises(ValueError):
        membership("EXAMPLE", "2026-07-09")


def test_calendar_recovers_budget_weekends_and_explicit_short_session():
    days = schedule({"2025-10-21", "2026-01-15"})
    assert days["2025-02-01"] == dict(open_minute=555, slots=375, kind="budget")
    assert days["2026-02-01"]["slots"] == 375
    assert days["2025-10-21"] == dict(open_minute=825, slots=60, kind="muhurat")
    assert "2026-01-15" not in days and "2026-01-18" not in days
    samples = minute_samples(reviewed_frame("2025-10-21", 825, 60), include_unlabelled=True)
    assert samples.bar_slot.tolist() == list(range(60))
    assert samples.feature_available.iloc[:3].sum() == 0


@pytest.mark.parametrize(
    "day,minute,slots,overrides",
    [
        ("2026-01-09", 555, 375, {}),
        ("2026-02-01", 555, 375, {}),
        ("2025-10-21", 825, 60, dict(train_end=date(2025, 9, 30), valid_start=date(2025, 10, 9))),
    ],
)
def test_reference_fees_reconcile_to_flat_ledger_on_regular_budget_and_short_sessions(
    day,
    minute,
    slots,
    overrides,
):
    frame = reviewed_frame(day, minute, slots)
    result = replay(frame, policy(**overrides))
    assert result.n_fills == 2 and len(result.snapshots) == slots
    assert result.fills[0]["timestamp"] == int(frame.open_time.iloc[1])
    assert result.fills[-1]["timestamp"] == int(frame.open_time.iloc[-1])
    rows = [
        ChargeTrade(
            date.fromisoformat(day),
            "EXAMPLE",
            row["order_id"],
            row["side"],
            D(row["quantity"]),
            D(row["price"]),
        )
        for row in result.fills
    ]
    expected = estimate_intraday_charges(rows)
    assert D(result.fees) == expected.total.quantize(D("1e-18"))
    assert sum(D(row["fee"]) for row in result.fills) + sum(
        D(row["amount"]) for row in result.fee_adjustments
    ) == D(result.fees)
    gross = sum(
        (
            D(r["quantity"]) * D(r["price"]) * (1 if r["side"] == "SELL" else -1)
            for r in result.fills
        ),
        D(0),
    )
    assert result.trace.snapshots[-1].equity == D(100000) + gross - D(result.fees)
    assert result.trace.positions[-1].quantity == 0


@pytest.mark.leakage
def test_future_exit_price_cannot_change_entry_fee_or_entry_quantity():
    original = reviewed_frame("2026-01-09")
    later = original.astype({name: float for name in ("open", "high", "low", "close")})
    later.loc[later.index >= 200, ["open", "high", "low", "close"]] *= 1.01
    first, second = replay(original, policy()), replay(later, policy())
    assert first.fills[0]["fee"] == second.fills[0]["fee"]
    assert first.fills[0]["quantity"] == second.fills[0]["quantity"]
    assert first.fills[0]["price"] == second.fills[0]["price"]


def test_partial_order_cap_and_stt_settlement_with_multiple_securities():
    book = IntradayChargeBook(D(2))
    rows = [
        ChargeTrade(date(2026, 3, 2), "EXAMPLE", "buy", "BUY", D(500), D(200)),
        ChargeTrade(date(2026, 3, 2), "EXAMPLE", "buy", "BUY", D(500), D(200)),
        ChargeTrade(date(2026, 3, 2), "EXAMPLE", "sell", "SELL", D(1000), D(200)),
    ]
    paid = sum(map(book.record, rows), D(0))
    estimate, adjustment = book.settle()
    assert estimate.brokerage == D(40)
    assert paid + adjustment == 2 * estimate.total
    with pytest.raises(ValueError, match="already settled"):
        book.settle()
    with pytest.raises(ValueError):
        book.record(rows[0])


def test_fee_refund_is_auditable_idempotent_and_cannot_create_money():
    ledger = PnLLedger(D(1000), Mode.BACKTEST, "INR", symbols=("EXAMPLE",))
    charge = FeeAdjustment(adjustment_id="day", timestamp=1, amount=D(10))
    assert ledger.adjust_fees(charge)
    assert not ledger.adjust_fees(charge)
    assert ledger.adjust_fees(FeeAdjustment(adjustment_id="refund", timestamp=2, amount=D(-2)))
    point = ledger.snapshot(2, {})
    assert point.cash == point.equity == D(992) and point.fees == D(8)
    assert point.realized_pnl == 0
    with pytest.raises(LedgerError, match="cannot exceed"):
        ledger.adjust_fees(FeeAdjustment(adjustment_id="bad", timestamp=3, amount=D(-9)))
    with pytest.raises(LedgerError, match="conflicting"):
        ledger.adjust_fees(charge.model_copy(update={"amount": D(11)}))


def test_adjusted_units_and_bad_daily_extremes_are_quarantined_without_rescaling():
    frame = reviewed_frame("2026-01-09")
    official = pd.Series(dict(TckrSymb="EXAMPLE", HghPric=101, LwPric=99))
    assert verify_price_day(frame, official, "EXAMPLE") == "PASS_SCALE_SCREEN"
    official.TckrSymb = "BAJFINANCE"
    assert verify_price_day(frame, official, "BAJFINANCE") == "UNRESOLVED_CAPITAL_ACTION_UNITS"
    official.TckrSymb = "EXAMPLE"
    official.HghPric = 1000
    assert verify_price_day(frame, official, "EXAMPLE") == "DAILY_SCALE_MISMATCH"
    assert frame.close.eq(100).all()  # No inferred factor changes source observations.


def test_v2_cannot_silently_reuse_v1_costs_or_session_policy():
    with pytest.raises(ValueError, match="v2 requires"):
        EquityResearchPolicy(version="nse_minute_research_v2", interval="1m")
    with pytest.raises(ValueError, match="v1 assumptions"):
        EquityResearchPolicy(session="reviewed_sessions_v2")
    old = replay(
        reviewed_frame("2026-01-09"),
        EquityResearchPolicy(version="nse_minute_research_v1", interval="1m"),
    )
    assert old.trace.snapshots[-1].equity == D(99800)
    assert old.fee_adjustments == ()
