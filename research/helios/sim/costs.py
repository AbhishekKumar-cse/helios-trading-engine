"""Explicit taker fees and per-side slippage applied to position turnover (ADR-005)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sqlalchemy import Connection

from helios.alpha.output import BoundedAlphaSeries
from helios.common.config import canonical_json, config_hash
from helios.common.project_config import FeesConfig, load_fees
from helios.sim.positions import GrossSimulation, SimulationError, simulate_gross


@dataclass(frozen=True)
class NetSimulation:
    gross: GrossSimulation
    fees_json: str
    fees_hash: str
    cost_bps: float
    table: pd.DataFrame


def apply_costs(gross: GrossSimulation, fees: FeesConfig | None = None) -> NetSimulation:
    """Charge abs(position change) once, including entry and flips, without inventing exits.

    The input comes from simulate_gross. Unknown turnover/costs remain unavailable;
    net return requires both gross return and cost. Keep a canonical fee snapshot
    because nested configuration dictionaries can otherwise be mutated by callers.
    No orders, results or market observations are persisted.
    """
    selected = load_fees() if fees is None else fees
    selected = FeesConfig.model_validate(selected.model_dump())
    bps = selected.cost_bps(gross.symbol)
    if not np.isfinite(bps):
        raise SimulationError("combined cost must be finite")
    result = gross.table.copy(deep=True)
    required = {"turnover", "turnover_available", "gross_return", "gross_available"}
    if not result.columns.is_unique or not required.issubset(result.columns):
        raise SimulationError("costs require gross simulation columns")
    for name in ("turnover_available", "gross_available"):
        if result[name].dtype != bool or result[name].isna().any():
            raise SimulationError("availability columns must be boolean")
    for name in ("turnover", "gross_return"):
        if (
            not pd.api.types.is_numeric_dtype(result[name].dtype)
            or pd.api.types.is_bool_dtype(result[name].dtype)
            or pd.api.types.is_complex_dtype(result[name].dtype)
        ):
            raise SimulationError("returns and turnover must be real numeric values")
    turnover = result.turnover.to_numpy(dtype=float, na_value=np.nan)
    returns = result.gross_return.to_numpy(dtype=float, na_value=np.nan)
    cost_mask = result.turnover_available.to_numpy(copy=True)
    gross_mask = result.gross_available.to_numpy(copy=True)
    if (cost_mask & (~np.isfinite(turnover) | (turnover < 0))).any():
        raise SimulationError("available turnover must be finite and non-negative")
    if (gross_mask & ~np.isfinite(returns)).any():
        raise SimulationError("available gross returns must be finite")
    with np.errstate(over="ignore", invalid="ignore"):
        cost = turnover * (bps / 10_000)
        net = returns - cost
    if (cost_mask & ~np.isfinite(cost)).any():
        raise SimulationError("cost overflow")
    net_mask = cost_mask & gross_mask
    if (net_mask & ~np.isfinite(net)).any():
        raise SimulationError("net return overflow")
    result["cost"] = np.where(cost_mask, cost, np.nan)
    result["cost_available"] = cost_mask
    result["net_return"] = np.where(net_mask, net, np.nan)
    result["net_available"] = net_mask
    return NetSimulation(gross, canonical_json(selected), config_hash(selected), bps, result)


def simulate_net(
    connection: Connection,
    *,
    experiment_id: int,
    alpha: BoundedAlphaSeries,
    bars: pd.DataFrame,
    interval: str,
    execution_lag: int = 1,
    fees: FeesConfig | None = None,
) -> NetSimulation:
    """Verify preregistration and calculate gross and net returns in memory."""
    return apply_costs(
        simulate_gross(
            connection,
            experiment_id=experiment_id,
            alpha=alpha,
            bars=bars,
            interval=interval,
            execution_lag=execution_lag,
        ),
        fees,
    )
