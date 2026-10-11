"""Net reference-exposure metrics with explicit periods and accounting conventions."""

from __future__ import annotations

from dataclasses import dataclass
from math import fsum, isfinite, sqrt
from typing import Literal

import numpy as np
import numpy.typing as npt
import pandas as pd
from pydantic import Field, StrictInt

from helios.common.config import HeliosConfig, canonical_json, config_hash
from helios.common.project_config import HorizonFamily, SplitsConfig, load_splits
from helios.data.klines import interval_us
from helios.sim.costs import NetSimulation
from helios.sim.positions import SimulationError, _times


class MetricsConfig(HeliosConfig):
    horizon_family: HorizonFamily
    periods_per_year: StrictInt = Field(gt=0)
    volatility_ddof: Literal[1] = 1
    risk_free_rate: Literal[0] = 0
    return_convention: Literal["arithmetic_reference_pnl_v1"] = "arithmetic_reference_pnl_v1"
    boundary_convention: Literal["entry_cost_in_first_interval_v1"] = (
        "entry_cost_in_first_interval_v1"
    )


@dataclass(frozen=True)
class ReturnMetrics:
    n_periods: int
    total_return: float
    mean_return: float | None
    annual_return: float | None
    period_volatility: float | None
    annual_volatility: float | None
    per_period_sharpe: float | None
    annual_sharpe: float | None


@dataclass(frozen=True)
class SimulationMetrics:
    metrics: ReturnMetrics
    config: MetricsConfig
    config_json: str
    config_hash: str
    splits_hash: str
    symbol: str
    experiment_id: int
    snapshot_id: str | None
    position_config_hash: str
    fees_hash: str
    code_commit: str
    dirty: bool


def return_metrics(returns: npt.ArrayLike, *, periods_per_year: int) -> ReturnMetrics:
    """Arithmetic total/annual net P&L; sample volatility; zero-risk-free Sharpe.

    Input must be complete observed periods. No dropping, compounding, zero filling,
    epsilon denominator or invented observation occurs. Undefined ratios are None.
    """
    if isinstance(periods_per_year, bool) or not isinstance(periods_per_year, int):
        raise SimulationError("periods_per_year must be a positive integer")
    if periods_per_year < 1:
        raise SimulationError("periods_per_year must be a positive integer")
    values = np.asarray(returns)
    if values.ndim != 1 or values.size == 0 or values.dtype.kind not in "iuf":
        raise SimulationError("metrics require non-empty one-dimensional real numeric returns")
    values = values.astype(np.float64, copy=True)
    if not np.isfinite(values).all():
        raise SimulationError("metrics require finite returns with complete availability")
    try:
        total = fsum(float(value) for value in values)
        mean = total / len(values)
        annual = mean * periods_per_year
        scale = float(np.max(np.abs(values)))
        # Scaling prevents squared tiny returns underflowing to a false zero variance.
        volatility = (
            None
            if len(values) < 2
            else 0.0
            if scale == 0
            else float(np.std(values / scale, ddof=1)) * scale
        )
        annual_volatility = None if volatility is None else volatility * sqrt(periods_per_year)
        sharpe = None if volatility is None or volatility == 0 else mean / volatility
        annual_sharpe = None if sharpe is None else sharpe * sqrt(periods_per_year)
    except (OverflowError, ValueError) as exc:
        raise SimulationError("metric arithmetic overflow") from exc
    if any(
        value is not None and not isfinite(value)
        for value in (total, mean, annual, volatility, annual_volatility, sharpe, annual_sharpe)
    ):
        raise SimulationError("metric arithmetic overflow")
    return ReturnMetrics(
        len(values), total, mean, annual, volatility, annual_volatility, sharpe, annual_sharpe
    )


def simulation_metrics(
    simulation: NetSimulation, *, splits: SplitsConfig | None = None
) -> SimulationMetrics:
    """Summarize a complete contiguous net simulation without persisting results.

    The initial row is an accounting boundary. Its net entry expense is assigned
    to the first realized interval for moments, and remains in total P&L. A lone
    boundary has a total only, with no invented annualization or return observation.
    """
    family = {"1h": HorizonFamily.HOURLY, "1m": HorizonFamily.MINUTE}.get(
        simulation.gross.config.interval
    )
    selected = load_splits() if splits is None else splits
    selected = SplitsConfig.model_validate(selected.model_dump())
    if family is None or family not in selected.families:
        raise SimulationError("metrics require a configured hourly or minute horizon family")
    config = MetricsConfig(
        horizon_family=family, periods_per_year=selected.families[family].periods_per_year
    )
    frame = simulation.table.copy(deep=True)
    required = {"open_time", "initial_boundary", "net_return", "net_available"}
    if frame.empty or not frame.columns.is_unique or not required.issubset(frame.columns):
        raise SimulationError("metrics require a non-empty net simulation table")
    for name in ("initial_boundary", "net_available"):
        if frame[name].dtype != bool or frame[name].isna().any():
            raise SimulationError("metric availability and boundary masks must be boolean")
    if not frame.initial_boundary.iloc[0] or frame.initial_boundary.iloc[1:].any():
        raise SimulationError("only the first row must be the initial accounting boundary")
    if not frame.net_available.all():
        raise SimulationError("metrics require complete net availability; no dropping or filling")
    times = _times(frame.open_time)
    period = interval_us(simulation.gross.config.interval)
    if (times % period != 0).any() or any(
        int(later) - int(earlier) != period
        for earlier, later in zip(times[:-1], times[1:], strict=True)
    ):
        raise SimulationError("metrics require contiguous periods on the declared UTC grid")
    column = frame.net_return
    if (
        not pd.api.types.is_numeric_dtype(column.dtype)
        or pd.api.types.is_bool_dtype(column.dtype)
        or pd.api.types.is_complex_dtype(column.dtype)
    ):
        raise SimulationError("net returns must be real numeric values")
    values = column.to_numpy(dtype=np.float64, na_value=np.nan, copy=True)
    if not np.isfinite(values).all():
        raise SimulationError("net returns must be finite")
    if len(values) == 1:
        metrics = ReturnMetrics(0, float(values[0]), None, None, None, None, None, None)
    else:
        observed = values[1:].copy()
        with np.errstate(over="ignore", invalid="ignore"):
            observed[0] += values[0]
        metrics = return_metrics(observed, periods_per_year=config.periods_per_year)
    gross = simulation.gross
    return SimulationMetrics(
        metrics,
        config,
        canonical_json(config),
        config_hash(config),
        config_hash(selected),
        gross.symbol,
        gross.experiment_id,
        gross.snapshot_id,
        gross.config_hash,
        simulation.fees_hash,
        gross.code_commit,
        gross.dirty,
    )
