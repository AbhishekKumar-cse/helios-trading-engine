"""UTC daily Sharpe and reference-P&L drawdown, turnover and directional hit rate."""

from __future__ import annotations

from dataclasses import dataclass
from math import fsum, isfinite
from typing import Literal

import numpy as np
import pandas as pd

from helios.common.config import HeliosConfig, canonical_json, config_hash
from helios.common.project_config import SplitsConfig
from helios.data.klines import interval_us
from helios.sim.costs import NetSimulation
from helios.sim.metrics import SimulationMetrics, return_metrics, simulation_metrics
from helios.sim.positions import SimulationError, Values, _times

DAY_US = 86_400_000_000


class DiagnosticsConfig(HeliosConfig):
    daily_min_days: Literal[30] = 30
    daily_periods_per_year: Literal[365] = 365
    daily_timestamp: Literal["row_open_time_utc"] = "row_open_time_utc"
    drawdown: Literal["additive_pnl_from_zero_v1"] = "additive_pnl_from_zero_v1"
    duration: Literal["peak_to_recovery_or_end_v1"] = "peak_to_recovery_or_end_v1"
    hit_rate: Literal["held_position_market_return_sign_v1"] = "held_position_market_return_sign_v1"


@dataclass(frozen=True)
class DailyPnL:
    day: str
    net_return: float
    n_periods: int
    expected_periods: int
    has_gaps: bool


@dataclass(frozen=True)
class DailyMetrics:
    days: tuple[DailyPnL, ...]
    n_days: int
    sharpe: float | None
    unavailable_reason: str | None


@dataclass(frozen=True)
class Drawdown:
    magnitude: float
    duration_periods: int
    duration_us: int


@dataclass(frozen=True)
class SimulationDiagnostics:
    base: SimulationMetrics
    config_json: str
    config_hash: str
    daily: DailyMetrics
    total_turnover: float
    mean_turnover: float | None
    drawdown: Drawdown
    hit_rate: float | None
    n_hit_periods: int


def _real(column: pd.Series) -> Values:
    if (
        not pd.api.types.is_numeric_dtype(column.dtype)
        or pd.api.types.is_bool_dtype(column.dtype)
        or pd.api.types.is_complex_dtype(column.dtype)
    ):
        raise SimulationError("diagnostics require real numeric values")
    values = column.to_numpy(dtype=float, na_value=np.nan, copy=True)
    if not np.isfinite(values).all():
        raise SimulationError("diagnostics require finite values")
    return values


def _complete(frame: pd.DataFrame, name: str) -> Values:
    mask = name + "_available"
    if name not in frame or mask not in frame:
        raise SimulationError(f"missing diagnostic column: {name}")
    if frame[mask].dtype != bool or not frame[mask].all():
        raise SimulationError(f"diagnostics require complete boolean {mask}")
    return _real(frame[name])


def daily_metrics(times: pd.Series, net_returns: pd.Series, *, interval: str) -> DailyMetrics:
    """Sum observed-period net P&L per UTC day; omit absent days and flag partial days.

    Unlike per-period Sharpe, gaps between known observations are permitted here,
    recorded rather than filled. Unknown observations must be resolved upstream.
    """
    if interval not in {"1h", "1m"}:
        raise SimulationError("daily metrics require hourly or minute observations")
    timestamps = _times(times)
    period = interval_us(interval)
    values = _real(net_returns)
    if len(timestamps) != len(values) or (timestamps % period != 0).any():
        raise SimulationError("daily observations must align on the UTC interval grid")
    groups = timestamps // DAY_US
    days = []
    expected = DAY_US // period
    for day in np.unique(groups):
        selected = values[groups == day]
        try:
            total = fsum(float(v) for v in selected)
        except OverflowError as exc:
            raise SimulationError("daily P&L overflow") from exc
        days.append(
            DailyPnL(
                pd.Timestamp(int(day) * DAY_US, unit="us", tz="UTC").date().isoformat(),
                total,
                len(selected),
                expected,
                len(selected) != expected,
            )
        )
    if len(days) < 30:
        return DailyMetrics(tuple(days), len(days), None, "fewer than 30 observed UTC days")
    sharpe = return_metrics([d.net_return for d in days], periods_per_year=365).annual_sharpe
    return DailyMetrics(
        tuple(days), len(days), sharpe, "zero daily variance" if sharpe is None else None
    )


def pnl_drawdown(times: pd.Series, net_returns: pd.Series, *, interval: str) -> Drawdown:
    """Peak-to-trough additive P&L from the known zero-capital-reference starting point.

    Initial entry expense is retained. Longest underwater duration includes recovery
    and unrecovered episodes; magnitude and duration may describe different episodes.
    """
    timestamps = _times(times)
    values = _real(net_returns)
    period = interval_us(interval)
    if not len(values) or len(values) != len(timestamps):
        raise SimulationError("drawdown requires aligned non-empty observations")
    if (timestamps % period != 0).any() or any(
        int(b) - int(a) != period for a, b in zip(timestamps[:-1], timestamps[1:], strict=True)
    ):
        raise SimulationError("drawdown requires contiguous periods")
    peak = cumulative = magnitude = 0.0
    peak_index = longest = 0
    underwater = False
    for index, value in enumerate(values):
        cumulative += float(value)
        if not isfinite(cumulative) or not isfinite(peak - cumulative):
            raise SimulationError("drawdown arithmetic overflow")
        if cumulative >= peak:
            if underwater:
                longest = max(longest, index - peak_index)
            peak, peak_index, underwater = cumulative, index, False
        else:
            underwater = True
            magnitude = max(magnitude, peak - cumulative)
            longest = max(longest, index - peak_index)
    return Drawdown(magnitude, longest, longest * period)


def simulation_diagnostics(
    simulation: NetSimulation, *, splits: SplitsConfig | None = None
) -> SimulationDiagnostics:
    base = simulation_metrics(simulation, splits=splits)
    frame = simulation.table.copy(deep=True)
    turnover = _complete(frame, "turnover")
    if (turnover < 0).any():
        raise SimulationError("turnover must be non-negative")
    try:
        total_turnover = fsum(float(v) for v in turnover)
    except OverflowError as exc:
        raise SimulationError("turnover overflow") from exc
    n = base.metrics.n_periods
    observed = frame.iloc[1:].copy()
    if n:
        observed_values = _real(observed.net_return)
        observed_values[0] += float(frame.net_return.iloc[0])
        observed["net_return"] = observed_values
    interval = simulation.gross.config.interval
    daily = daily_metrics(observed.open_time, observed.net_return, interval=interval)
    hit_rate = None
    known = np.zeros(n, dtype=bool)
    for name in ("held_position", "period_return"):
        mask = "held_available" if name == "held_position" else "return_available"
        if name not in observed or mask not in observed or observed[mask].dtype != bool:
            raise SimulationError("hit rate requires numeric positions/returns and boolean masks")
        _real(observed.loc[observed[mask], name])
        if name == "held_position":
            known = observed[mask].to_numpy(copy=True)
        else:
            known &= observed[mask].to_numpy()
    if n and known.all():
        held, market = _real(observed.held_position), _real(observed.period_return)
        hit_rate = float(np.mean(np.sign(held) == np.sign(market)))
    config = DiagnosticsConfig()
    return SimulationDiagnostics(
        base,
        canonical_json(config),
        config_hash(config),
        daily,
        total_turnover,
        total_turnover / n if n else None,
        pnl_drawdown(frame.open_time, frame.net_return, interval=interval),
        hit_rate,
        int(known.sum()),
    )
