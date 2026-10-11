"""Recorded G1–G6 selection decisions; validity and promotion stay distinct (108)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite
from typing import Literal

from helios.common.config import canonical_json, config_hash
from helios.common.project_config import GatesConfig, SplitsConfig, load_gates
from helios.registry.results import Split
from helios.sim.cost_sensitivity import CostSensitivity
from helios.sim.diagnostics import simulation_diagnostics
from helios.sim.fitness import FitnessResult, fitness_result
from helios.sim.metrics import SimulationMetrics
from helios.sim.positions import SimulationError
from helios.sim.splits import SplitEvaluation, split_window
from helios.sim.stability import StabilityResult
from helios.sim.validity import InvalidReason


@dataclass(frozen=True)
class GateOutcome:
    gate: str
    passed: bool
    value: float | bool | None
    threshold: float | bool | tuple[float, float]
    comparison: str
    reason: str | None

    @property
    def status(self) -> Literal["PASS", "FAIL"]:
        return "PASS" if self.passed else "FAIL"


@dataclass(frozen=True)
class GateReport:
    status: Literal["EVALUATED", "REJECTED", "INVALID"]
    outcomes: tuple[GateOutcome, ...]
    gate_config_json: str
    gate_config_hash: str
    base: SimulationMetrics | None = None
    invalid_reasons: tuple[InvalidReason, ...] = ()

    @property
    def all_passed(self) -> bool:
        return self.status == "EVALUATED" and all(g.passed for g in self.outcomes)


def _config(gates: GatesConfig | None) -> GatesConfig:
    selected = load_gates() if gates is None else gates
    selected = GatesConfig.model_validate(selected.model_dump())
    if any(isinstance(v, float) and not isfinite(v) for v in selected.model_dump().values()):
        raise SimulationError("gate thresholds must be finite")
    return selected


def gate_decisions(
    *,
    sharpe: float | None,
    fitness: float | None,
    turnover: float | None,
    split: Split,
    positive_fraction: float | None,
    cost_stress_sharpe: float | None,
    gates: GatesConfig | None = None,
) -> GateReport:
    """Pure comparison kernel; callers needing lineage use evaluate_gates instead."""
    selected = _config(gates)
    split = Split(split)
    for value in (sharpe, fitness, turnover, positive_fraction, cost_stress_sharpe):
        if value is not None and (isinstance(value, bool) or not isfinite(value)):
            raise SimulationError("gate evidence must be finite numeric values or None")
    if turnover is not None and turnover < 0:
        raise SimulationError("gate turnover cannot be negative")
    if positive_fraction is not None and not 0 <= positive_fraction <= 1:
        raise SimulationError("positive fraction must lie between zero and one")

    def above(name: str, value: float | None, threshold: float) -> GateOutcome:
        passed = value is not None and value > threshold
        return GateOutcome(
            name,
            passed,
            value,
            threshold,
            ">",
            None if passed else "unavailable" if value is None else "threshold_not_met",
        )

    oos = split in (Split.VALID, Split.TEST)
    g3_passed = turnover is not None and selected.turnover_min < turnover < selected.turnover_max
    outcomes = (
        above("G1", sharpe, selected.sharpe_min),
        above("G2", fitness, selected.fitness_min),
        GateOutcome(
            "G3",
            g3_passed,
            turnover,
            (selected.turnover_min, selected.turnover_max),
            "lower < value < upper",
            None if g3_passed else "unavailable" if turnover is None else "threshold_not_met",
        ),
        GateOutcome(
            "G4",
            oos or not selected.require_out_of_sample,
            oos,
            selected.require_out_of_sample,
            "out_of_sample_required",
            "disabled_by_recorded_config"
            if not selected.require_out_of_sample
            else None
            if oos
            else "in_sample",
        ),
        above("G5", positive_fraction, selected.stability_min_positive_fraction),
        above("G6", cost_stress_sharpe, selected.cost_stress_sharpe_min),
    )
    return GateReport(
        "EVALUATED" if all(g.passed for g in outcomes) else "REJECTED",
        outcomes,
        canonical_json(selected),
        config_hash(selected),
    )


def evaluate_gates(
    evaluation: SplitEvaluation,
    *,
    fitness: FitnessResult | None = None,
    stability: StabilityResult | None = None,
    costs: CostSensitivity | None = None,
    gates: GatesConfig | None = None,
) -> GateReport:
    """Compare matching split diagnostics; passing is not authorization to promote."""
    selected = _config(gates)
    if not evaluation.validity.valid:
        blank = gate_decisions(
            sharpe=None,
            fitness=None,
            turnover=None,
            split=evaluation.window.split,
            positive_fraction=None,
            cost_stress_sharpe=None,
            gates=selected,
        )
        return replace(
            blank,
            status="INVALID",
            invalid_reasons=evaluation.validity.reasons,
            outcomes=tuple(
                replace(g, passed=False, reason="invalid_alpha") for g in blank.outcomes
            ),
        )
    diagnostics = evaluation.diagnostics
    if diagnostics is None:
        raise SimulationError("valid evaluation requires diagnostics")
    base = diagnostics.base
    if (
        base.splits_hash != evaluation.window.splits_hash
        or base.config.horizon_family != evaluation.window.family
    ):
        raise SimulationError("split evidence lineage mismatch")
    if evaluation.window.split is Split.TEST:
        access = evaluation.test_access
        if access is None or (access.alpha_id, access.version, access.snapshot_id) != (
            evaluation.alpha_id,
            evaluation.version,
            base.snapshot_id,
        ):
            raise SimulationError("TEST gate evidence requires its matching access reservation")
    split_config = SplitsConfig.model_validate_json(evaluation.window.splits_json)
    if evaluation.window != split_window(
        evaluation.window.split,
        interval=evaluation.window.interval,
        horizon_periods=evaluation.window.horizon_periods,
        splits=split_config,
    ):
        raise SimulationError("split window configuration mismatch")
    simulation = evaluation.simulation
    if simulation is None:
        raise SimulationError("valid gate evaluation requires its net simulation")
    times = simulation.table.open_time
    if (times < evaluation.window.start_us).any() or (times >= evaluation.window.end_us).any():
        raise SimulationError("simulation timestamps are outside the declared split")
    if simulation_diagnostics(simulation, splits=split_config) != diagnostics:
        raise SimulationError("simulation diagnostics lineage mismatch")
    if (
        evaluation.validity.symbol != base.symbol
        or evaluation.validity.n_periods != base.metrics.n_periods
    ):
        raise SimulationError("validity and simulation observations mismatch")
    fitness_value = None
    if fitness is not None:
        if fitness != fitness_result(diagnostics, gates=selected):
            raise SimulationError("Fitness evidence lineage/config mismatch")
        fitness_value = fitness.value
    positive = None
    if stability is not None:
        if stability.base != base:
            raise SimulationError("stability evidence lineage mismatch")
        # Do not improve stability by omitting undefined observed monthly ratios.
        if selected.stability_subperiod == "month" and stability.n_defined_months == len(
            stability.months
        ):
            positive = stability.positive_month_fraction
    stress = None
    if costs is not None:
        baseline = next((p for p in costs.points if p.multiplier == 1), None)
        if costs.base_fees_hash != base.fees_hash or baseline is None or baseline.metrics != base:
            raise SimulationError("cost evidence lineage mismatch")
        point = next(
            (p for p in costs.points if p.multiplier == selected.cost_stress_multiplier), None
        )
        if point is not None:
            # Stress fees legitimately differ; the rest of the source lineage must match.
            if replace(point.metrics, metrics=base.metrics, fees_hash=base.fees_hash) != base:
                raise SimulationError("stress evidence source lineage mismatch")
            stress = point.metrics.metrics.annual_sharpe
    result = gate_decisions(
        sharpe=base.metrics.annual_sharpe,
        fitness=fitness_value,
        turnover=diagnostics.mean_turnover,
        split=evaluation.window.split,
        positive_fraction=positive,
        cost_stress_sharpe=stress,
        gates=selected,
    )
    return replace(result, base=base)
