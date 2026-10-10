"""Lagged positions and gross simple returns; no costs or metrics yet (step 095)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import numpy.typing as npt
import pandas as pd
from pydantic import Field, StrictInt, field_validator
from sqlalchemy import Connection

from helios.alpha.output import BoundedAlphaSeries, OutputConvention, bound_alpha
from helios.common.config import HeliosConfig, config_hash
from helios.common.lineage import git_commit, git_is_dirty
from helios.data.klines import KlineFormatError, interval_us
from helios.registry.experiments import require_open_experiment

Values = npt.NDArray[np.float64]
Mask = npt.NDArray[np.bool_]


class SimulationError(ValueError):
    """Invalid simulation alignment, prices or execution controls."""


class PositionConfig(HeliosConfig):
    interval: str
    execution_lag: StrictInt = Field(default=1, ge=1, lt=2**63)
    position_scale: float = Field(gt=0, allow_inf_nan=False)
    initial_position: Literal[0] = 0
    return_convention: Literal["simple_close_to_close_v1"] = "simple_close_to_close_v1"

    @field_validator("interval")
    @classmethod
    def _interval(cls, value: str) -> str:
        try:
            interval_us(value)
        except KlineFormatError as exc:
            raise ValueError(str(exc)) from exc
        return value


@dataclass(frozen=True)
class GrossSimulation:
    symbol: str
    experiment_id: int
    config: PositionConfig
    config_hash: str
    code_commit: str
    dirty: bool
    snapshot_id: str | None
    table: pd.DataFrame


def _times(times: pd.Series) -> npt.NDArray[np.int64]:
    if (
        not pd.api.types.is_integer_dtype(times.dtype)
        or pd.api.types.is_bool_dtype(times.dtype)
        or times.isna().any()
        or not times.is_monotonic_increasing
        or times.duplicated().any()
        or (times < np.iinfo(np.int64).min).any()
        or (times > np.iinfo(np.int64).max).any()
    ):
        raise SimulationError("timestamps must be chronological unique int64 UTC microseconds")
    return times.to_numpy(dtype=np.int64, copy=True)


def _delay(values: Values, available: Mask, steps: Mask, periods: int) -> tuple[Values, Mask]:
    result = np.full(len(values), np.nan, dtype=np.float64)
    usable = np.zeros(len(values), dtype=bool)
    if periods == 0:
        return values.copy(), available.copy()
    if periods < len(values):
        # Each missing interval invalidates every lag spanning it, without filling history.
        bad = np.concatenate(([0], np.cumsum(~steps[1:])))
        contiguous = bad[periods:] == bad[:-periods]
        usable[periods:] = available[:-periods] & contiguous
        result[periods:] = np.where(usable[periods:], values[:-periods], np.nan)
    return result, usable


def _position_table(
    alpha: BoundedAlphaSeries, bars: pd.DataFrame, config: PositionConfig
) -> pd.DataFrame:
    """Pure arithmetic kernel; the public entry point enforces experiment registration."""
    if not isinstance(alpha, BoundedAlphaSeries):
        raise SimulationError("simulation requires bounded alpha with a stored output convention")
    if not {"open_time", "close"}.issubset(bars.columns) or not bars.columns.is_unique:
        raise SimulationError("bars require unique open_time and close columns")
    if bars.empty or not bars.index.is_unique:
        raise SimulationError("bars require non-empty rows with a unique index")
    if "symbol" in bars and not bars["symbol"].eq(alpha.symbol).all():
        raise SimulationError("bars must contain only the alpha symbol")
    times = _times(bars["open_time"])
    alpha_times = _times(alpha.open_time)
    period = interval_us(config.interval)
    if (times % period != 0).any() or (alpha_times % period != 0).any():
        raise SimulationError("timestamps must lie on the declared UTC interval grid")
    if not np.isin(alpha_times, times).all():
        raise SimulationError("alpha timestamps must belong to the supplied bars")
    bounded = bound_alpha(alpha, output=alpha.output)
    price = bars["close"]
    if (
        not pd.api.types.is_numeric_dtype(price.dtype)
        or pd.api.types.is_bool_dtype(price.dtype)
        or pd.api.types.is_complex_dtype(price.dtype)
    ):
        raise SimulationError("close prices must be real numeric values")
    closes = price.to_numpy(dtype=np.float64, na_value=np.nan, copy=True)
    if (np.isfinite(closes) & (closes <= 0)).any():
        raise SimulationError("finite close prices must be positive")
    aligned = pd.Series(bounded.values.to_numpy(), index=alpha_times).reindex(times)
    aligned_mask = (
        pd.Series(bounded.available.to_numpy(), index=alpha_times)
        .reindex(times, fill_value=False)
        .to_numpy(dtype=bool)
    )
    values = aligned.to_numpy(dtype=np.float64)
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        target = np.clip(values / config.position_scale, -1, 1)
    target_mask = aligned_mask & np.isfinite(target)
    target = np.where(target_mask, target, np.nan)
    steps = np.zeros(len(times), dtype=bool)
    steps[1:] = np.diff(times) == period
    position, position_mask = _delay(target, target_mask, steps, config.execution_lag - 1)
    # No execution before the first usable scheduled target: remain explicitly flat
    # during startup/warm-up. After trading starts, unavailable targets stay unknown.
    usable_executions = np.flatnonzero(position_mask)
    start = int(usable_executions[0]) if len(usable_executions) else len(times)
    position[:start] = config.initial_position
    position_mask[:start] = True
    held, held_mask = _delay(position, position_mask, steps, 1)
    held[: min(start + 1, len(times))] = config.initial_position
    held_mask[: min(start + 1, len(times))] = True
    period_return = np.full(len(times), np.nan, dtype=np.float64)
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        period_return[1:] = closes[1:] / closes[:-1] - 1
    return_mask = np.zeros(len(times), dtype=bool)
    return_mask[1:] = steps[1:] & np.isfinite(closes[1:]) & np.isfinite(closes[:-1])
    return_mask &= np.isfinite(period_return)
    period_return = np.where(return_mask, period_return, np.nan)
    with np.errstate(over="ignore", invalid="ignore"):
        gross = held * period_return
    gross_mask = held_mask & return_mask & np.isfinite(gross)
    # Initial accounting boundary, not a fabricated market return. Entry costs can
    # be charged here in step 096 instead of vanishing behind a first-row NaN.
    gross[0] = 0.0
    gross_mask[0] = True
    boundary = np.zeros(len(times), dtype=bool)
    boundary[0] = True
    turnover = np.full(len(times), np.nan, dtype=np.float64)
    turnover_mask = position_mask & held_mask
    turnover[turnover_mask] = np.abs(position[turnover_mask] - held[turnover_mask])
    if position_mask[0]:
        turnover[0] = abs(position[0] - config.initial_position)
        turnover_mask[0] = True
    return pd.DataFrame(
        {
            "open_time": times,
            "initial_boundary": boundary,
            "alpha": values,
            "alpha_available": aligned_mask,
            "target_position": target,
            "target_available": target_mask,
            "position": position,
            "position_available": position_mask,
            "held_position": held,
            "held_available": held_mask,
            "period_return": period_return,
            "return_available": return_mask,
            "gross_return": np.where(gross_mask, gross, np.nan),
            "gross_available": gross_mask,
            "turnover": turnover,
            "turnover_available": turnover_mask,
        },
        index=bars.index.copy(),
    )


def simulate_gross(
    connection: Connection,
    *,
    experiment_id: int,
    alpha: BoundedAlphaSeries,
    bars: pd.DataFrame,
    interval: str,
    execution_lag: int = 1,
) -> GrossSimulation:
    """Apply positions from prior decisions to realized intervals, never current signals.

    Verify a real open pre-registered experiment before computation. Returns only an
    in-memory gross simulation; no result, metrics, promotion or trade is written.
    Row t's close/previous-close simple return corresponds to the forward interval
    starting at t-1. Positions are scheduled after the current close; default lag 1
    therefore earns return t with position t-1, without shifting returns twice.
    """
    if isinstance(experiment_id, bool) or not isinstance(experiment_id, int) or experiment_id < 1:
        raise SimulationError("a positive registered experiment_id is required")
    experiment = require_open_experiment(connection, experiment_id)
    if not isinstance(alpha, BoundedAlphaSeries):
        raise SimulationError("simulation requires bounded alpha with output metadata")
    output = OutputConvention.model_validate(alpha.output.model_dump())
    config = PositionConfig(
        interval=interval, execution_lag=execution_lag, position_scale=output.position_scale
    )
    commit, dirty = git_commit(), git_is_dirty()
    table = _position_table(alpha, bars, config)
    return GrossSimulation(
        alpha.symbol,
        experiment_id,
        config,
        config_hash(config),
        commit,
        dirty,
        experiment.snapshot_id,
        table,
    )
