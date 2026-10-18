"""One-symbol reference runner using the shared strategy/risk/OMS/venue/ledger."""

from decimal import Decimal, localcontext
from types import SimpleNamespace

from helios.backtest.config import BacktestConfig
from helios.backtest.equity_config import EquityBacktestConfig
from helios.common.types import (
    AlphaValue,
    Bar,
    BookView,
    ExecutionReport,
    Mode,
    NewOrder,
    Order,
    OrderAction,
    PnLSnapshot,
    Position,
    ReasonCode,
    Record,
    Reject,
    RiskDecision,
    RiskState,
)
from helios.equities.charges import IntradayChargeBook
from helios.sim.event_loop import BarEventLoop, BarOpen
from helios.sim.ledger import FeeAdjustment, PnLLedger
from helios.sim.loss_risk import DailyRisk, TripStore
from helios.sim.oms import OrderManagementSystem
from helios.sim.paper import BarPaperVenue
from helios.sim.portfolio_risk import PortfolioSnapshot
from helios.sim.price_risk import PriceObservation
from helios.sim.strategy import WORKING_STATES, BarStrategy


class ReplayTrace(Record):
    orders: tuple[Order, ...]
    reports: tuple[ExecutionReport, ...]
    snapshots: tuple[PnLSnapshot, ...]
    positions: tuple[Position, ...]
    marks: tuple[Decimal, ...]
    decisions: tuple[RiskDecision, ...]
    tail: tuple[NewOrder, ...]
    fee_adjustments: tuple[FeeAdjustment, ...] = ()


def simulate(
    config: BacktestConfig | EquityBacktestConfig,
    bars: tuple[Bar, ...],
    signals: tuple[AlphaValue, ...],
    store: TripStore,
) -> ReplayTrace:
    if not bars or len(signals) != len(bars):
        raise ValueError("every input bar requires an explicit typed alpha status")
    for bar, signal in zip(bars, signals, strict=True):
        if (
            bar.symbol != config.symbol
            or bar.snapshot_id != config.snapshot_id
            or not config.start_us <= bar.open_time < config.end_us
            or signal.symbol != bar.symbol
            or signal.timestamp != bar.ingest_time
            or signal.lineage.snapshot_id != config.snapshot_id
            or signal.lineage.alpha_id != config.alpha_id
            or signal.lineage.alpha_version != config.alpha_version
        ):
            raise ValueError("bar/signal/config identity or availability mismatch")
    signal_map = {s.timestamp: s for s in signals}
    if len(signal_map) != len(signals):
        raise ValueError("signal timestamps must be unique")
    equity_market = isinstance(config, EquityBacktestConfig)
    charge_book = (
        IntradayChargeBook(Decimal(str(config.cost_multiplier)))
        if isinstance(config, EquityBacktestConfig)
        and config.policy.charge_policy == "intraday_reference_v2"
        else None
    )
    ledger = PnLLedger(
        config.strategy.capital,
        Mode.BACKTEST,
        "INR" if equity_market else "USDT",
        symbols=(config.symbol,) if equity_market else (),
        mark_reference=config.mark_reference,
    )
    strategy = BarStrategy(config.strategy)
    clock, price = bars[0].open_time, bars[0].open
    histories: list[PriceObservation] = []
    snapshots: list[PnLSnapshot] = []
    positions: list[Position] = []
    marks: list[Decimal] = []
    reports: list[ExecutionReport] = []
    decisions: list[RiskDecision] = []
    day, baseline, last_equity = -1, config.strategy.capital, config.strategy.capital

    def books() -> dict[str, BookView]:
        # These reference prices are explicitly bar proxies, never observed quotes.
        return {
            config.symbol: BookView(
                symbol=config.symbol,
                timestamp=clock,
                sequence=0,
                best_bid=price,
                best_ask=price,
                stale=False,
            )
        }

    def equity() -> PnLSnapshot:
        return ledger.snapshot(clock, books())

    def state() -> RiskState:
        with localcontext() as context:
            context.prec = 100
            daily = equity().equity - baseline
        return RiskState(
            timestamp=clock,
            halted=store.is_tripped(config.run_id),
            daily_pnl=daily,
            limits_hash=risk.limits_hash,
        )

    def portfolio() -> PortfolioSnapshot:
        return PortfolioSnapshot(
            timestamp=clock,
            snapshot_id=config.snapshot_id,
            positions=(ledger.position(config.symbol),),
            open_orders=oms.snapshot(),
            marks=(histories[-1],),
        )

    risk = DailyRisk(config.risk, state, lambda _: tuple(histories), portfolio, store)
    counter = 0

    def identifier() -> str:
        nonlocal counter
        counter += 1
        return f"{config.run_id}:{counter}" if equity_market else str(counter)

    oms = OrderManagementSystem(config.run_id, Mode.BACKTEST, risk, id_factory=identifier)
    venue = BarPaperVenue(
        Mode.BACKTEST,
        config.fees,
        venue_id=config.run_id if equity_market else "bar-paper",
        quote_asset="INR" if equity_market else "USDT",
        charge_book=charge_book,
    )

    def on_report(report: ExecutionReport) -> None:
        oms.on_report(report)
        ledger.on_report(report)
        reports.append(report)

    venue.subscribe_reports(on_report)

    def observe(timestamp: int, value: Decimal) -> None:
        nonlocal clock, price, day, baseline, last_equity
        clock, price = timestamp, value
        if clock // 86_400_000_000 != day:
            day, baseline = clock // 86_400_000_000, last_equity
        if histories and histories[-1].timestamp == clock:
            histories.pop()
        histories.append(
            PriceObservation(
                symbol=config.symbol, timestamp=clock, price=price, snapshot_id=config.snapshot_id
            )
        )
        last_equity = equity().equity

    def opened(opening: BarOpen) -> None:
        observe(opening.timestamp, opening.price)
        venue.on_open(opening)

    def closed(bar: Bar) -> None:
        venue.on_bar(bar)
        observe(bar.ingest_time, bar.close)
        snapshot = equity()
        snapshots.append(snapshot)
        positions.append(ledger.position(config.symbol))
        marks.append(price)
        if state().daily_pnl <= config.risk.daily_loss_limit.copy_negate() and not store.is_tripped(
            config.run_id
        ):
            risk.trip(clock, "backtest_loss_guard", ReasonCode.DAILY_LOSS_LIMIT)

    def decide(bar: Bar) -> list[OrderAction]:
        actions = strategy.on_update(
            signal_map[bar.ingest_time],
            books()[config.symbol],
            ledger.position(config.symbol),
            tuple(o for o in oms.snapshot() if o.state in WORKING_STATES),
            state(),
        )
        ready: list[OrderAction] = []
        for action in actions:
            decision = risk.check(action)
            decisions.append(decision)
            if decision.accepted:
                ready.append(action)
        return ready

    def act(action: OrderAction, opening: BarOpen) -> None:
        observe(opening.timestamp, opening.price)
        decision = risk.check(action)
        decisions.append(decision)
        if not decision.accepted:
            return
        assert decision.authorised is not None
        created = oms.submit(decision.authorised)
        accepted = venue.submit_order(oms.mark_pending(created.order_id, clock))
        if isinstance(accepted, Reject):
            raise ValueError("paper venue refused an authorized OMS handoff")
        venue.dispatch_reports()

    tail = BarEventLoop().run(
        SimpleNamespace(events=lambda: iter(bars)), decide, act, opened=opened, closed=closed
    )
    adjustments: tuple[FeeAdjustment, ...] = ()
    if charge_book is not None:
        if tail or venue.snapshot_open_orders():
            raise ValueError("cannot settle fees while execution remains pending")
        _, amount = charge_book.settle()
        adjustment = FeeAdjustment(
            adjustment_id=config.run_id + ":stt", timestamp=clock, amount=amount
        )
        ledger.adjust_fees(adjustment)
        snapshots[-1] = equity()
        adjustments = (adjustment,)
    return ReplayTrace(
        orders=oms.snapshot(),
        reports=tuple(reports),
        snapshots=tuple(snapshots),
        positions=tuple(positions),
        marks=tuple(marks),
        decisions=tuple(decisions),
        tail=tuple(p.action for p in tail if isinstance(p.action, NewOrder)),
        fee_adjustments=adjustments,
    )
