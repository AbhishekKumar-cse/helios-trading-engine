"""NSE session replays through the shared strategy/risk/OMS/venue/ledger."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal, localcontext
from typing import Any
from uuid import uuid4

import pandas as pd

from helios.alpha.output import BoundedAlphaSeries
from helios.backtest.engine import ReplayTrace, simulate
from helios.backtest.equity_config import EquityBacktestConfig
from helios.common.config import config_hash
from helios.common.project_config import HorizonFamily
from helios.common.types import AlphaStatus, AlphaValue, Bar, DecisionLineage, Mode
from helios.equities.config import EquityResearchPolicy
from helios.equities.inputs import EquityInputs
from helios.sim.loss_risk import DailyRiskLimits, RiskTrip
from helios.sim.portfolio_risk import PositionLimits
from helios.sim.strategy import ShareBarStrategyConfig


class SessionTrips:
    def __init__(self) -> None:
        self.events: list[RiskTrip] = []

    def is_tripped(self, scope: str) -> bool:
        return any(event.scope == scope for event in self.events)

    def trip(self, event: RiskTrip) -> None:
        if not self.is_tripped(event.scope):
            self.events.append(event)


@dataclass(frozen=True)
class SessionReplay:
    day: str
    net_return: float
    turnover: float
    fees: str
    n_fills: int
    fills: tuple[dict[str, Any], ...]
    snapshots: tuple[dict[str, Any], ...]
    trace: ReplayTrace
    fee_adjustments: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class SessionEvidence:
    day: str
    net_return: float
    turnover: float
    fees: str
    n_fills: int
    fills: tuple[dict[str, Any], ...]
    snapshots: tuple[dict[str, Any], ...]
    fee_adjustments: tuple[dict[str, Any], ...] = ()


def replay_pair(
    arguments: tuple[Any, ...],
    *,
    state_changes_only: bool = False,
    feature_set_version: str | None = None,
) -> tuple[SessionEvidence, SessionEvidence]:
    """Pure worker boundary: no database, shared state or retained parent traces."""
    frame, alpha, policy, snapshot, identifier, commit, stress, model = arguments
    evidence = []
    for multiplier in (1.0, stress):
        result = replay_session(
            frame,
            alpha,
            policy,
            snapshot_id=snapshot,
            alpha_id=identifier,
            code_commit=commit,
            multiplier=multiplier,
            model_hash=model,
            state_changes_only=state_changes_only,
            feature_set_version=feature_set_version,
        )
        evidence.append(
            SessionEvidence(
                result.day,
                result.net_return,
                result.turnover,
                result.fees,
                result.n_fills,
                result.fills,
                result.snapshots,
                result.fee_adjustments,
            )
        )
    return evidence[0], evidence[1]


def eligible_sessions(
    inputs: EquityInputs, *, interval: str = "1h"
) -> tuple[list[pd.DataFrame], list[dict[str, str]]]:
    if interval not in ("1h", "1m"):
        raise ValueError("unsupported equity frequency")
    sessions, excluded = [], []
    for day in inputs.expected_sessions:
        frame = inputs.bars.loc[inputs.bars.session_date == day].sort_values("open_time")
        local = frame.timestamp.dt.tz_convert("Asia/Kolkata")
        minutes = (local.dt.hour * 60 + local.dt.minute).tolist()
        expected = (
            [555 + 60 * slot for slot in range(7)] if interval == "1h" else list(range(555, 930))
        )
        if interval == "1m" and "session_slots" in frame and not frame.empty:
            if frame.session_slots.nunique() != 1 or frame.session_open_minute.nunique() != 1:
                raise ValueError("session schedule changed within one day")
            opening, slots = (
                int(frame.session_open_minute.iloc[0]),
                int(frame.session_slots.iloc[0]),
            )
            expected = list(range(opening, opening + slots))
        if minutes != expected:
            excluded.append(dict(day=day, reason="missing_or_nonstandard_bar_slots"))
            continue
        if (local.dt.second != 0).any() or (local.dt.microsecond != 0).any():
            excluded.append(dict(day=day, reason="nonstandard_bar_timestamp"))
            continue
        if (
            (frame.low > frame[["open", "close"]].min(axis=1))
            | (frame.high < frame[["open", "close"]].max(axis=1))
        ).any():
            excluded.append(dict(day=day, reason="inconsistent_source_ohlc"))
            continue
        if (frame.iloc[1:].volume <= 0).any():
            excluded.append(dict(day=day, reason="zero_volume_execution_bar"))
            continue
        sessions.append(frame.reset_index(drop=True))
    return sessions, excluded


def replay_session(
    frame: pd.DataFrame,
    alpha: BoundedAlphaSeries,
    policy: EquityResearchPolicy,
    *,
    snapshot_id: str,
    alpha_id: str,
    code_commit: str,
    multiplier: float = 1,
    model_hash: str | None = None,
    state_changes_only: bool = False,
    feature_set_version: str | None = None,
) -> SessionReplay:
    if state_changes_only and policy.version != "nse_minute_research_v2":
        raise ValueError("state-change execution requires the explicit v2 minute cost policy")
    symbol = alpha.symbol
    day = str(frame.session_date.iloc[0])
    slots = (
        int(frame.session_slots.iloc[0])
        if policy.version == "nse_minute_research_v2"
        else policy.session_slots
    )
    run_id = "nse_" + uuid4().hex[:24]
    # Carried cash can have all18 monetary decimals; fractional allocation must
    # fit the same risk-limit precision without rounding/injecting account cash.
    with localcontext() as context:
        context.prec = 100
        notional = (policy.capital * policy.max_weight).quantize(
            Decimal("1e-18"), rounding=ROUND_DOWN
        )
    config = EquityBacktestConfig(
        run_id=run_id,
        alpha_id=alpha_id,
        snapshot_id=snapshot_id,
        symbol=symbol,
        start_us=int(frame.open_time.iloc[0]),
        end_us=int(frame.open_time.iloc[0])
        + (slots if policy.interval == "1m" else 375) * 60_000_000,
        policy=policy,
        fees=policy.fees(symbol, multiplier),
        cost_multiplier=multiplier,
        strategy=ShareBarStrategyConfig(
            strategy_id=run_id,
            capital=policy.capital,
            max_weight=policy.max_weight,
            rebalance_threshold=Decimal(0),
            quantity_step=Decimal(1),
            mode=Mode.BACKTEST,
        ),
        risk=DailyRiskLimits(
            scope=run_id,
            daily_loss_limit=policy.capital,
            max_gross_exposure=notional * 2,
            instruments=(
                PositionLimits(
                    symbol=symbol,
                    max_order_notional=notional * 3,
                    max_position_notional=notional * 2,
                    price_band_fraction=Decimal("0.2"),
                    median_window=1,
                    max_price_age_us=0,
                ),
            ),
        ),
    )
    lineage = DecisionLineage(
        alpha_id=alpha_id,
        alpha_version=1,
        feature_set_version=feature_set_version or policy.feature_set_version,
        horizon_family=HorizonFamily.HOURLY if policy.interval == "1h" else HorizonFamily.MINUTE,
        code_commit=code_commit,
        config_hash=config_hash(policy),
        snapshot_id=snapshot_id,
        seed=policy.seed,
        model_hash=model_hash,
    )
    lookup = {
        int(clock): (float(value) if ok else None)
        for clock, value, ok in zip(alpha.open_time, alpha.values, alpha.available, strict=True)
    }
    bars, signals = [], []
    previous_value: float | None = None
    entries = 0
    for slot, row in enumerate(frame.itertuples(index=False)):
        opening = int(frame.open_time.iloc[slot])
        duration = (60 if slot < 6 else 15) if policy.interval == "1h" else 1
        closing = opening + duration * 60_000_000
        bars.append(
            Bar(
                calendar=(
                    "nse_reviewed_v2"
                    if policy.version == "nse_minute_research_v2"
                    else "nse_regular_v1"
                ),
                symbol=symbol,
                source="yahoo_nse" if policy.interval == "1h" else "upstox_public_minute",
                sequence=slot,
                interval=policy.interval,
                open_time=opening,
                ingest_time=closing,
                recorded_close_time=closing - 1,
                snapshot_id=snapshot_id,
                open=Decimal(str(row.open)),
                high=Decimal(str(row.high)),
                low=Decimal(str(row.low)),
                close=Decimal(str(row.close)),
                volume=Decimal(str(row.volume)),
            )
        )
        # A calendar-known flat target exits at the final observed bar opening.
        value = 0.0 if slot >= slots - 2 else lookup.get(opening)
        if state_changes_only and value is not None:
            if value not in (0.0, 1.0):
                raise ValueError("state-change research supports binary long/flat targets only")
            current = value
            if current == 1.0 and previous_value != 1.0:
                entries += 1
                if entries > 1:
                    raise ValueError("paper research permits at most one entry per session")
            # A held state creates no fresh notional target. The existing strategy
            # consequently preserves the actual filled whole-share quantity.
            if current == previous_value:
                value = None
            previous_value = current
        signals.append(
            AlphaValue(
                symbol=symbol,
                timestamp=closing,
                status=AlphaStatus.OK if value is not None else AlphaStatus.UNAVAILABLE,
                value=value,
                lineage=lineage,
            )
        )
    trace = simulate(config, tuple(bars), tuple(signals), SessionTrips())
    if trace.positions[-1].quantity != 0 or trace.tail:
        raise ValueError("session did not finish flat; do not invent a liquidation fill")
    fills = tuple(report.fill for report in trace.reports if report.fill is not None)
    if any(
        fill.fee_asset != "INR" or fill.quantity != fill.quantity.to_integral_value()
        for fill in fills
    ):
        raise ValueError("equity fills require INR accounting and whole shares")
    if any(position.quantity < 0 for position in trace.positions):
        raise ValueError("equity pilot is long-only")
    with localcontext() as context:
        context.prec = 100
        net = (trace.snapshots[-1].equity - policy.capital) / policy.capital
        turnover = sum((fill.quantity * fill.price for fill in fills), Decimal(0)) / policy.capital
    return SessionReplay(
        day,
        float(net),
        float(turnover),
        str(trace.snapshots[-1].fees),
        len(fills),
        tuple(fill.model_dump(mode="json") for fill in fills),
        tuple(point.model_dump(mode="json") for point in trace.snapshots),
        trace,
        tuple(point.model_dump(mode="json") for point in trace.fee_adjustments),
    )
