"""NSE session replays through the shared strategy/risk/OMS/venue/ledger."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext
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


def eligible_sessions(inputs: EquityInputs) -> tuple[list[pd.DataFrame], list[dict[str, str]]]:
    sessions, excluded = [], []
    for day in inputs.expected_sessions:
        frame = inputs.bars.loc[inputs.bars.session_date == day].sort_values("open_time")
        local = frame.timestamp.dt.tz_convert("Asia/Kolkata")
        minutes = (local.dt.hour * 60 + local.dt.minute).tolist()
        if minutes != [555 + 60 * slot for slot in range(7)]:
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
) -> SessionReplay:
    symbol = alpha.symbol
    day = str(frame.session_date.iloc[0])
    run_id = "nse_" + uuid4().hex[:24]
    notional = policy.capital * policy.max_weight
    config = EquityBacktestConfig(
        run_id=run_id,
        alpha_id=alpha_id,
        snapshot_id=snapshot_id,
        symbol=symbol,
        start_us=int(frame.open_time.iloc[0]),
        end_us=int(frame.open_time.iloc[0]) + 375 * 60_000_000,
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
        feature_set_version="nse_session_features_v1",
        horizon_family=HorizonFamily.HOURLY,
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
    for slot, row in enumerate(frame.itertuples(index=False)):
        opening = int(frame.open_time.iloc[slot])
        closing = opening + (60 if slot < 6 else 15) * 60_000_000
        bars.append(
            Bar(
                calendar="nse_regular_v1",
                symbol=symbol,
                source="yahoo_nse",
                sequence=slot,
                interval="1h",
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
        # A calendar-known flat target at 15:15 exits at the observed partial-hour open.
        value = 0.0 if slot >= 5 else lookup.get(opening)
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
    )
