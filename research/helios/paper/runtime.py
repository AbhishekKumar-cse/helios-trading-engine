"""Receipt-clock PAPER wiring of the existing strategy/risk/OMS/venue/ledger."""

import json
from decimal import Decimal, localcontext

import pandas as pd
from pydantic import TypeAdapter

from helios.alpha.definition import AlphaDefinition
from helios.alpha.output import evaluate_definition
from helios.backtest.engine import ReplayTrace
from helios.common.config import config_hash
from helios.common.project_config import HorizonFamily
from helios.common.types import (
    AlphaStatus,
    AlphaValue,
    BookView,
    CancelOrder,
    DecisionLineage,
    ExecutionReport,
    Mode,
    OrderState,
    PnLSnapshot,
    Position,
    Price,
    ReasonCode,
    Reject,
    RiskDecision,
    RiskState,
)
from helios.data.live_klines import ClosedKline, KlineStreamError, decode_closed_kline
from helios.equities.features import minute_samples
from helios.equities.live import EquityClosedCandle, yahoo_public_quote
from helios.equities.paper_config import EquityPaperConfig
from helios.features import basic  # noqa: F401
from helios.features.runner import FeatureFrame, compute_features
from helios.ml.equity_pilot import features_for
from helios.paper.config import PaperConfig
from helios.sim.event_loop import BarOpen
from helios.sim.ledger import PnLLedger
from helios.sim.loss_risk import DailyRisk, TripStore
from helios.sim.oms import OrderManagementSystem
from helios.sim.paper import BarPaperVenue
from helios.sim.portfolio_risk import PortfolioSnapshot
from helios.sim.price_risk import PriceObservation
from helios.sim.strategy import WORKING_STATES, BarStrategy


class PaperSafetyStop(ValueError):
    pass


def public_price(
    raw: str | bytes, symbols: tuple[str, ...], received: int
) -> tuple[int, int, Decimal] | None:
    """Only in-progress last prices; completed OHLC never becomes an opening fill."""
    if decode_closed_kline(raw, symbols, received_time=received) is not None:
        return None
    try:
        envelope = json.loads(raw)
        event = envelope.get("data", envelope)
        kline = event["k"]
        opened, ended, exchange = kline["t"], kline["T"], event["E"]
        if (
            any(type(v) is not int or v < 0 for v in (opened, ended, exchange))
            or opened % 60_000
            or ended != opened + 59_999
            or exchange < opened
            or not isinstance(kline["c"], str)
        ):
            raise ValueError("invalid in-progress time or price")
        value = Decimal(kline["c"])
        if not value.is_finite() or value <= 0 or len(value.as_tuple().digits) > 38:
            raise ValueError("invalid in-progress price")
        TypeAdapter(Price).validate_python(value)
        return opened * 1000, exchange * 1000, value
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        raise KlineStreamError("malformed in-progress price observation") from exc


class PaperRuntime:
    def __init__(
        self,
        config: PaperConfig | EquityPaperConfig,
        definition: AlphaDefinition,
        code_commit: str,
        store: TripStore,
    ) -> None:
        if (
            definition.alpha_id != config.alpha_id
            or definition.version != config.alpha_version
            or definition.horizon_family is not HorizonFamily.MINUTE
            or (isinstance(config, PaperConfig) and definition.expression != "-sign(log_return_1)")
            or (isinstance(config, EquityPaperConfig) and definition.expression is None)
        ):
            raise ValueError("integration policy requires a matching registered minute formula")
        self.config, self.definition, self.store = config, definition, store
        self.clock, self.price = 0, Decimal(1)
        self.day, self.baseline, self.last_equity = (
            -1,
            config.strategy.capital,
            config.strategy.capital,
        )
        self.history: list[PriceObservation] = []
        self.bars: list[ClosedKline | EquityClosedCandle] = []
        self.signals: list[AlphaValue] = []
        self.reports: list[ExecutionReport] = []
        self.snapshots: list[PnLSnapshot] = []
        self.positions: list[Position] = []
        self.marks: list[Decimal] = []
        self.decisions: list[RiskDecision] = []
        self.ledger = PnLLedger(
            config.strategy.capital,
            Mode.PAPER,
            "INR" if isinstance(config, EquityPaperConfig) else "USDT",
            symbols=(config.symbol,) if isinstance(config, EquityPaperConfig) else (),
            mark_reference="public_last_price_proxy",
        )
        self.strategy = BarStrategy(config.strategy)
        self.risk = DailyRisk(
            config.risk, self.state, lambda _: tuple(self.history), self.portfolio, store
        )
        self.oms = OrderManagementSystem(config.run_id, Mode.PAPER, self.risk)
        self.venue = BarPaperVenue(
            Mode.PAPER,
            config.fees,
            quote_asset="INR" if isinstance(config, EquityPaperConfig) else "USDT",
        )
        self.venue.subscribe_reports(self.on_report)
        self.lineage = DecisionLineage(
            alpha_id=definition.alpha_id,
            alpha_version=definition.version,
            feature_set_version=definition.feature_set_version,
            horizon_family=HorizonFamily.MINUTE,
            code_commit=code_commit,
            config_hash=config_hash(config),
            snapshot_id=config.stream_id,
            seed=0,
        )

    def book(self) -> BookView:
        return BookView(
            symbol=self.config.symbol,
            timestamp=self.clock,
            sequence=0,
            best_bid=self.price,
            best_ask=self.price,
            stale=False,
        )

    def equity(self) -> PnLSnapshot:
        return self.ledger.snapshot(self.clock, {self.config.symbol: self.book()})

    def state(self) -> RiskState:
        with localcontext() as context:
            context.prec = 100
            pnl = self.equity().equity - self.baseline
        return RiskState(
            timestamp=self.clock,
            halted=self.store.is_tripped(self.config.run_id),
            daily_pnl=pnl,
            limits_hash=self.risk.limits_hash,
        )

    def portfolio(self) -> PortfolioSnapshot:
        return PortfolioSnapshot(
            timestamp=self.clock,
            snapshot_id=self.config.stream_id,
            positions=(self.ledger.position(self.config.symbol),),
            open_orders=self.oms.snapshot(),
            marks=(self.history[-1],),
        )

    def observe(self, received: int, event: int, price: Decimal) -> None:
        if (
            received <= self.clock
            or received - event > self.config.max_event_skew_us
            or event - received > min(5_000_000, self.config.max_event_skew_us)
        ):
            self.stop("nonmonotone_or_stale_feed", max(received, self.clock))
        self.clock, self.price = received, price
        if self.day != received // 86_400_000_000:
            self.day, self.baseline = received // 86_400_000_000, self.last_equity
        self.history.append(
            PriceObservation(
                symbol=self.config.symbol,
                timestamp=received,
                price=price,
                snapshot_id=self.config.stream_id,
            )
        )
        self.history = self.history[-168:]
        self.last_equity = self.equity().equity
        if self.state().daily_pnl <= self.config.risk.daily_loss_limit.copy_negate():
            self.risk.trip(self.clock, "paper_loss_guard", ReasonCode.DAILY_LOSS_LIMIT)
            raise PaperSafetyStop("daily loss guard latched")

    def stop(self, actor: str, timestamp: int | None = None) -> None:
        self.halt(actor, timestamp)
        raise PaperSafetyStop(actor)

    def check_health(self, now: int, *, started_at: int) -> None:
        """Poll even when neither feed emits a usable observation.

        Allow one minute plus the skew budget to receive the first fresh close.
        After startup, silence cannot keep a pending intent alive indefinitely.
        A kill never depends on receiving a quote or having a pending order.
        """
        if self.store.is_tripped(self.config.run_id):
            self.stop("operator_kill", max(now, self.clock))
        if isinstance(self.config, EquityPaperConfig) and self.config.delayed_public:
            if any(
                o.state in WORKING_STATES
                and now - o.request.timestamp > self.config.max_intent_age_us
                for o in self.oms.snapshot()
            ):
                self.stop("stale_or_halted_pending_intent", max(now, self.clock))
            if self.bars and now - self.bars[-1].event_time > self.config.max_event_skew_us:
                self.stop("delayed_candle_age_exceeded", max(now, self.clock))
        anchor = self.clock or started_at
        allowance = self.config.max_event_skew_us + (0 if self.clock else 60_000_000)
        if now < anchor or now - anchor > allowance:
            self.stop("feed_silence_or_clock_regression", max(now, self.clock))

    def halt(self, actor: str, timestamp: int | None = None) -> None:
        clock = max(self.clock, self.clock if timestamp is None else timestamp)
        self.risk.trip(clock, actor)
        for order in self.oms.snapshot():
            if order.state not in (OrderState.ACCEPTED, OrderState.PARTIALLY_FILLED):
                continue
            self.oms.request_cancel(order.order_id, clock)
            response = self.venue.cancel(
                CancelOrder(
                    request_id=order.order_id + ":stop",
                    order_id=order.order_id,
                    symbol=self.config.symbol,
                    timestamp=clock,
                    mode=Mode.PAPER,
                    lineage=order.request.lineage,
                )
            )
            if isinstance(response, Reject):
                raise PaperSafetyStop("cannot confirm cancellation of simulated pending intent")
            self.venue.dispatch_reports()

    def on_report(self, report: ExecutionReport) -> None:
        self.oms.on_report(report)
        self.ledger.on_report(report)
        self.reports.append(report)

    def snapshot(self) -> None:
        self.snapshots.append(self.equity())
        self.positions.append(self.ledger.position(self.config.symbol))
        self.marks.append(self.price)
        self.last_equity = self.snapshots[-1].equity
        if self.state().daily_pnl <= self.config.risk.daily_loss_limit.copy_negate():
            self.risk.trip(self.clock, "paper_loss_guard", ReasonCode.DAILY_LOSS_LIMIT)
            raise PaperSafetyStop("daily loss guard latched after fill")

    def closed(self, bar: ClosedKline | EquityClosedCandle) -> None:
        equity_market = isinstance(self.config, EquityPaperConfig)
        if equity_market != isinstance(bar, EquityClosedCandle):
            self.stop("equity_feed_type_mismatch", max(self.clock, bar.received_time))
        if (
            equity_market
            and self.bars
            and pd.Timestamp(bar.open_time, unit="us", tz="UTC").date()
            != pd.Timestamp(self.bars[-1].open_time, unit="us", tz="UTC").date()
        ):
            if self.ledger.position(self.config.symbol).quantity != 0:
                self.stop(
                    "unreconciled_overnight_equity_position", max(self.clock, bar.received_time)
                )
            self.bars.clear()
        if bar.symbol != self.config.symbol or (
            self.bars and bar.open_time != self.bars[-1].open_time + 60_000_000
        ):
            self.stop("closed_bar_gap_or_identity", max(self.clock, bar.received_time))
        self.observe(bar.received_time, bar.event_time, bar.close)
        self.bars.append(bar)
        frame = pd.DataFrame(
            [
                dict(
                    open_time=b.open_time,
                    open=float(b.open),
                    high=float(b.high),
                    low=float(b.low),
                    close=float(b.close),
                    volume=float(b.volume),
                )
                for b in self.bars[-32 if equity_market else -2 :]
            ]
        )
        if equity_market:
            frame["symbol"] = bar.symbol
            frame["timestamp"] = pd.to_datetime(frame.open_time, unit="us", utc=True)
            frame["available_at"] = frame.timestamp + pd.Timedelta(minutes=1)
            frame["session_date"] = frame.timestamp.dt.tz_convert("Asia/Kolkata").dt.strftime(
                "%Y-%m-%d"
            )
            frame["full_bar"] = True
            samples = minute_samples(frame, include_unlabelled=True)
            values = samples[list(features_for("60m"))]
            masks = pd.DataFrame({name: samples.feature_available for name in values})
            features = FeatureFrame(bar.symbol, samples.open_time, values.where(masks), masks)
        else:
            features = compute_features(frame, "1m", names=["log_return_1"], symbol=bar.symbol)
        alpha = evaluate_definition(self.definition, features, interval="1m")
        available = bool(alpha.available.iloc[-1])
        local = pd.Timestamp(bar.received_time, unit="us", tz="UTC").tz_convert("Asia/Kolkata")
        closing_target = equity_market and local.hour * 60 + local.minute >= 925
        signal = AlphaValue(
            symbol=bar.symbol,
            timestamp=bar.received_time,
            status=AlphaStatus.OK if available or closing_target else AlphaStatus.UNAVAILABLE,
            value=0.0 if closing_target else float(alpha.values.iloc[-1]) if available else None,
            lineage=self.lineage,
        )
        self.signals.append(signal)
        for action in self.strategy.on_update(
            signal,
            self.book(),
            self.ledger.position(bar.symbol),
            tuple(o for o in self.oms.snapshot() if o.state in WORKING_STATES),
            self.state(),
        ):
            decision = self.risk.check(action)
            self.decisions.append(decision)
            if decision.accepted:
                assert decision.authorised is not None
                order = self.oms.submit(decision.authorised)
                response = self.venue.submit_order(
                    self.oms.mark_pending(order.order_id, self.clock)
                )
                if isinstance(response, Reject):
                    self.stop("venue_rejected_authorized_order")
                self.venue.dispatch_reports()
        self.snapshot()

    def message(self, raw: str | bytes, received: int) -> None:
        quote = (
            yahoo_public_quote(raw, self.config.symbol)
            if isinstance(self.config, EquityPaperConfig)
            else public_price(raw, (self.config.symbol,), received)
        )
        if quote is None:
            return
        opened, event, price = quote
        if not self.bars or opened <= self.bars[-1].open_time:
            return
        delayed = isinstance(self.config, EquityPaperConfig) and self.config.delayed_public
        if (not delayed and opened != self.bars[-1].open_time + 60_000_000) or received < opened:
            self.stop("live_price_gap_or_future_clock", max(self.clock, received))
        if delayed and received - self.bars[-1].event_time > self.config.max_event_skew_us:
            self.stop("delayed_candle_age_exceeded", max(self.clock, received))
        self.observe(received, event, price)
        working = tuple(o for o in self.oms.snapshot() if o.state in WORKING_STATES)
        if working:
            if self.store.is_tripped(self.config.run_id) or any(
                received - o.request.timestamp > self.config.max_intent_age_us for o in working
            ):
                self.stop("stale_or_halted_pending_intent")
            if isinstance(self.config, EquityPaperConfig) and any(
                event <= order.request.timestamp for order in working
            ):
                if delayed:
                    # A repeated delayed price cannot execute a newer intent. Wait
                    # for a genuine later trade; check_health still expires intents.
                    return
                self.stop("equity_quote_predates_pending_intent")
            self.venue.on_public_price(
                BarOpen(self.config.symbol, received, price, self.config.stream_id)
            )
            self.snapshot()

    def trace(self) -> ReplayTrace:
        return ReplayTrace(
            orders=self.oms.snapshot(),
            reports=tuple(self.reports),
            snapshots=tuple(self.snapshots),
            positions=tuple(self.positions),
            marks=tuple(self.marks),
            decisions=tuple(self.decisions),
            tail=(),
        )
