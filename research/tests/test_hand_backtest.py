"""Independent fixed spreadsheet vs real strategy/risk/OMS/venue/ledger (148)."""

import csv
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace

from test_common_types import lineage

from helios.common.types import AlphaStatus, AlphaValue, Bar, BookView, Mode, RiskState
from helios.sim.event_loop import BarEventLoop
from helios.sim.ledger import PnLLedger
from helios.sim.loss_risk import DailyRisk, DailyRiskLimits
from helios.sim.oms import OrderManagementSystem
from helios.sim.paper import BarPaperVenue
from helios.sim.portfolio_risk import PortfolioSnapshot, PositionLimits
from helios.sim.price_risk import PriceObservation
from helios.sim.strategy import BarStrategy, BarStrategyConfig

FIXTURE = Path(__file__).parent / "fixtures/backtest/ten_bars_three_trades.csv"
H = 3_600_000_000


def replay(rows):
    # Only these input columns enter execution; expected accounting stays outside.
    bars = tuple(
        Bar(
            symbol="BTCUSDT",
            source="synthetic-hand-fixture",
            sequence=i,
            open_time=i * H,
            ingest_time=(i + 1) * H,
            interval="1h",
            snapshot_id="snapshot",
            **{name: D(row[name]) for name in ("open", "high", "low", "close", "volume")},
        )
        for i, row in enumerate(rows)
    )
    signals = [row["decision_alpha"] for row in rows]
    limits = DailyRiskLimits(
        scope="hand",
        instruments=(
            PositionLimits(
                symbol="BTCUSDT",
                max_order_notional=D(1000),
                max_position_notional=D(1000),
                price_band_fraction=D(1),
                median_window=1,
                max_price_age_us=0,
            ),
        ),
        max_gross_exposure=D(2000),
        daily_loss_limit=D(500),
    )
    store = SimpleNamespace(is_tripped=lambda scope: False, trip=lambda event: None)
    ledger = PnLLedger(D(1000), Mode.BACKTEST)
    clock, price = 0, D(100)
    snapshots, positions, reports, histories = [], [], [], []

    def state():
        snapshot = ledger.snapshot(clock, books())
        return RiskState(
            timestamp=clock,
            halted=False,
            daily_pnl=snapshot.equity - D(1000),
            limits_hash=risk.limits_hash,
        )

    def books():
        return {
            "BTCUSDT": BookView(
                symbol="BTCUSDT",
                timestamp=clock,
                sequence=0,
                best_bid=price,
                best_ask=price,
                stale=False,
            )
        }

    def portfolio():
        return PortfolioSnapshot(
            timestamp=clock,
            snapshot_id="snapshot",
            positions=(ledger.position("BTCUSDT"),),
            open_orders=oms.snapshot(),
            marks=(histories[-1],),
        )

    risk = DailyRisk(limits, state, lambda symbol: tuple(histories), portfolio, store)
    oms = OrderManagementSystem(
        "hand", Mode.BACKTEST, risk, id_factory=lambda: str(len(oms.snapshot()))
    )
    venue = BarPaperVenue(Mode.BACKTEST)
    venue.subscribe_reports(oms.on_report)
    venue.subscribe_reports(ledger.on_report)
    venue.subscribe_reports(reports.append)
    strategy = BarStrategy(
        BarStrategyConfig(
            capital=D(1000), max_weight=D(".5"), strategy_id="hand", rebalance_threshold=D(0)
        )
    )

    def observe(timestamp, observed_price):
        nonlocal clock, price
        clock, price = timestamp, observed_price
        if histories and histories[-1].timestamp == clock:
            histories.pop()
        histories.append(
            PriceObservation(symbol="BTCUSDT", timestamp=clock, price=price, snapshot_id="snapshot")
        )

    def opened(opening):
        observe(opening.timestamp, opening.price)
        venue.on_open(opening)

    def closed(bar):
        venue.on_bar(bar)
        observe(bar.ingest_time, bar.close)
        snapshots.append(ledger.snapshot(clock, books()))
        positions.append(ledger.position("BTCUSDT"))

    def decide(bar):
        value = signals[bar.sequence]
        alpha = AlphaValue(
            symbol="BTCUSDT",
            timestamp=clock,
            lineage=lineage(),
            status=AlphaStatus.OK if value else AlphaStatus.UNAVAILABLE,
            value=float(value) if value else None,
        )
        return strategy.on_update(
            alpha,
            books()["BTCUSDT"],
            ledger.position("BTCUSDT"),
            tuple(venue.snapshot_open_orders()),
            state(),
        )

    def act(action, opening):
        observe(opening.timestamp, opening.price)
        decision = risk.check(action)
        assert decision.accepted
        order = oms.submit(decision.authorised)
        assert (
            venue.submit_order(oms.mark_pending(order.order_id, clock)).order_id == order.order_id
        )
        venue.dispatch_reports()

    tail = BarEventLoop().run(
        SimpleNamespace(events=lambda: iter(bars)), decide, act, opened=opened, closed=closed
    )
    return snapshots, positions, reports, tail


def test_all_ten_rows_equal_independent_spreadsheet_exactly():
    with FIXTURE.open() as handle:
        rows = list(csv.DictReader(handle))
    snapshots, positions, reports, tail = replay(rows)
    assert len(rows) == len(snapshots) == 10 and not tail
    fills = [r.fill for r in reports if r.fill is not None]
    assert len(fills) == 3
    assert [f.timestamp for f in fills] == [H, 4 * H, 7 * H]
    for row, position, snapshot in zip(rows, positions, snapshots, strict=True):
        assert position.quantity == D(row["position_quantity"])
        assert (position.average_entry_price or D(0)) == D(row["average_cost"])
        for field, column in (
            ("cash", "cash"),
            ("equity", "equity"),
            ("realized_pnl", "realized_pnl"),
            ("unrealized_pnl", "unrealized_pnl"),
            ("fees", "fees_total"),
        ):
            assert getattr(snapshot, field) == D(row[column]), (row["bar"], field)
        assert snapshot.equity - 1000 == D(row["net_pnl"])
    for row, fill in zip([r for r in rows if r["fill_side"]], fills, strict=True):
        assert fill.side.value == row["fill_side"]
        assert fill.quantity == D(row["fill_quantity"])
        assert fill.price == D(row["fill_price"]) and fill.fee == D(row["fill_fee"])


def test_later_bars_cannot_change_earlier_fills_or_accounting():
    with FIXTURE.open() as handle:
        rows = list(csv.DictReader(handle))
    first = replay(rows)
    changed = [row.copy() for row in rows]
    changed[8].update(close="80", low="75")
    second = replay(changed)
    assert first[0][:8] == second[0][:8]
    assert first[1][:8] == second[1][:8]
    assert first[2] == second[2]
