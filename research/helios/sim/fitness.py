"""ADR-002 Fitness with explicit constants and preserved net-simulation lineage."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt
from typing import Literal

from pydantic import Field

from helios.common.config import HeliosConfig, canonical_json, config_hash
from helios.common.project_config import GatesConfig, load_gates
from helios.sim.diagnostics import SimulationDiagnostics
from helios.sim.positions import SimulationError


class FitnessConfig(HeliosConfig):
    formula: Literal["sharpe_sqrt_abs_annual_return_over_turnover_v1"] = (
        "sharpe_sqrt_abs_annual_return_over_turnover_v1"
    )
    turnover_floor: float = Field(default=0.125, gt=0, allow_inf_nan=False)


@dataclass(frozen=True)
class FitnessResult:
    diagnostics: SimulationDiagnostics
    value: float | None
    denominator: float | None
    config_json: str
    config_hash: str
    gate_config_json: str
    gate_config_hash: str


def fitness(
    annual_sharpe: float | None,
    annual_return: float | None,
    mean_turnover: float | None,
    *,
    floor: float = 0.125,
) -> float | None:
    """Annual net Sharpe * sqrt(abs(arithmetic annual net return) / max(turnover, floor))."""
    for name, value in (
        ("Sharpe", annual_sharpe),
        ("annual return", annual_return),
        ("turnover", mean_turnover),
        ("floor", floor),
    ):
        if value is not None and (isinstance(value, bool) or not isfinite(value)):
            raise SimulationError(f"Fitness {name} must be finite and numeric")
    if floor <= 0 or (mean_turnover is not None and mean_turnover < 0):
        raise SimulationError("Fitness requires positive floor and non-negative turnover")
    if annual_sharpe is None or annual_return is None or mean_turnover is None:
        return None
    value = annual_sharpe * sqrt(abs(annual_return) / max(mean_turnover, floor))
    if not isfinite(value):
        raise SimulationError("Fitness arithmetic overflow")
    return value


def fitness_result(
    diagnostics: SimulationDiagnostics, *, gates: GatesConfig | None = None
) -> FitnessResult:
    selected = load_gates() if gates is None else gates
    selected = GatesConfig.model_validate(selected.model_dump())
    config = FitnessConfig(turnover_floor=selected.fitness_turnover_floor)
    metrics = diagnostics.base.metrics
    value = fitness(
        metrics.annual_sharpe,
        metrics.annual_return,
        diagnostics.mean_turnover,
        floor=config.turnover_floor,
    )
    denominator = (
        None
        if diagnostics.mean_turnover is None
        else max(diagnostics.mean_turnover, config.turnover_floor)
    )
    return FitnessResult(
        diagnostics,
        value,
        denominator,
        canonical_json(config),
        config_hash(config),
        canonical_json(selected),
        config_hash(selected),
    )
