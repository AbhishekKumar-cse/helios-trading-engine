"""Five-point fee/slippage stress curve with unchanged execution and exact lineage."""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import fsum, isfinite
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from helios.common.config import HeliosConfig, canonical_json, config_hash
from helios.common.project_config import FeesConfig, SplitsConfig, load_fees, load_splits
from helios.sim.costs import apply_costs
from helios.sim.metrics import SimulationMetrics, simulation_metrics
from helios.sim.positions import GrossSimulation, SimulationError


class CostSweepConfig(HeliosConfig):
    multipliers: tuple[float, ...] = Field(default=(0.5, 1.0, 2.0, 3.0, 4.0), min_length=5)
    convention: Literal["scale_all_fee_and_slippage_bps_v1"] = "scale_all_fee_and_slippage_bps_v1"

    @field_validator("multipliers", mode="before")
    @classmethod
    def _no_boolean(cls, value: object) -> object:
        if isinstance(value, (list, tuple)) and any(isinstance(v, bool) for v in value):
            raise ValueError("cost multipliers cannot be boolean")
        return value

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if any(not isfinite(v) or v <= 0 for v in self.multipliers):
            raise ValueError("cost multipliers must be positive and finite")
        if any(a >= b for a, b in zip(self.multipliers[:-1], self.multipliers[1:], strict=True)):
            raise ValueError("cost multipliers must be unique and ascending")
        return self


@dataclass(frozen=True)
class CostPoint:
    multiplier: float
    cost_bps: float
    total_cost: float
    fees_json: str
    metrics: SimulationMetrics


@dataclass(frozen=True)
class CostSensitivity:
    config_json: str
    config_hash: str
    base_fees_json: str
    base_fees_hash: str
    points: tuple[CostPoint, ...]

    @property
    def cost_stress_sharpe(self) -> float | None:
        """ADR-002/005's 2x-cost annual family Sharpe; no gate decision."""
        return next(
            (p.metrics.metrics.annual_sharpe for p in self.points if p.multiplier == 2), None
        )


def cost_sensitivity(
    gross: GrossSimulation,
    *,
    fees: FeesConfig | None = None,
    config: CostSweepConfig | None = None,
    splits: SplitsConfig | None = None,
) -> CostSensitivity:
    selected_fees = load_fees() if fees is None else fees
    selected_fees = FeesConfig.model_validate(selected_fees.model_dump())
    selected_splits = load_splits() if splits is None else splits
    selected_splits = SplitsConfig.model_validate(selected_splits.model_dump())
    source = replace(gross, table=gross.table.copy(deep=True))
    selected = (
        CostSweepConfig() if config is None else CostSweepConfig.model_validate(config.model_dump())
    )
    # Canonical snapshots isolate nested dictionaries from caller mutation.
    base_json, base_hash = canonical_json(selected_fees), config_hash(selected_fees)
    points = []
    for multiplier in selected.multipliers:
        values = selected_fees.model_dump()
        values.update(
            maker_fee_bps=selected_fees.maker_fee_bps * multiplier,
            taker_fee_bps=selected_fees.taker_fee_bps * multiplier,
            slippage_bps={s: v * multiplier for s, v in selected_fees.slippage_bps.items()},
        )
        scaled = FeesConfig.model_validate(values)
        net = apply_costs(source, scaled)
        metrics = simulation_metrics(net, splits=selected_splits)
        try:
            total = fsum(float(v) for v in net.table.cost)
        except OverflowError as exc:
            raise SimulationError("cost sweep arithmetic overflow") from exc
        points.append(CostPoint(multiplier, net.cost_bps, total, net.fees_json, metrics))
    return CostSensitivity(
        canonical_json(selected), config_hash(selected), base_json, base_hash, tuple(points)
    )
