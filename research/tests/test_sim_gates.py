"""Strict G1–G6 boundaries, crafted simulations and evidence consistency."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from test_sim_costs import gross
from test_sim_positions import HOUR, inputs, table
from test_sim_stability import feature

from helios.common.project_config import load_gates
from helios.registry.results import Split
from helios.sim.cost_sensitivity import CostSweepConfig, cost_sensitivity
from helios.sim.costs import apply_costs
from helios.sim.diagnostics import simulation_diagnostics
from helios.sim.fitness import fitness_result
from helios.sim.gates import evaluate_gates, gate_decisions
from helios.sim.positions import SimulationError
from helios.sim.splits import SplitEvaluation, split_window
from helios.sim.stability import fit_volatility_regimes, stability_report
from helios.sim.validity import InvalidReason, alpha_validity


def decisions(**changes):
    return gate_decisions(
        **(
            {
                "sharpe": 1.5,
                "fitness": 1.4,
                "turnover": 0.2,
                "split": Split.VALID,
                "positive_fraction": 0.75,
                "cost_stress_sharpe": 0.5,
            }
            | changes
        )
    )


@pytest.mark.parametrize(
    "gate,field,value",
    [
        ("G1", "sharpe", 1.0),
        ("G2", "fitness", 1.0),
        ("G3", "turnover", 0.01),
        ("G3", "turnover", 0.70),
        ("G4", "split", Split.TRAIN),
        ("G5", "positive_fraction", 0.5),
        ("G6", "cost_stress_sharpe", 0.0),
    ],
)
def test_every_gate_fails_at_its_exact_boundary(gate, field, value) -> None:
    result = decisions(**{field: value})
    assert result.status == "REJECTED" and not result.all_passed
    assert [g.gate for g in result.outcomes if not g.passed] == [gate]
    assert next(g for g in result.outcomes if g.gate == gate).status == "FAIL"


def test_all_passes_and_configuration_changes_are_visible() -> None:
    result = decisions()
    assert result.all_passed and result.status == "EVALUATED"
    assert [g.gate for g in result.outcomes] == ["G1", "G2", "G3", "G4", "G5", "G6"]
    gates = load_gates().model_copy(update={"require_out_of_sample": False})
    disabled = decisions(split=Split.TRAIN, gates=gates)
    assert disabled.all_passed and disabled.outcomes[3].reason == "disabled_by_recorded_config"
    assert result.gate_config_hash != disabled.gate_config_hash
    assert result.outcomes[2].threshold == (0.01, 0.70)


@pytest.mark.parametrize(
    "field", ["sharpe", "fitness", "turnover", "positive_fraction", "cost_stress_sharpe"]
)
def test_missing_metric_fails_and_nonfinite_is_not_a_pass(field) -> None:
    assert not decisions(**{field: None}).all_passed
    for bad in (np.nan, np.inf, True):
        with pytest.raises(SimulationError, match="finite"):
            decisions(**{field: bad})


def evidence():
    start = int(pd.Timestamp("2023-01-31T21:00Z").timestamp() * 1_000_000)
    times = [start + i * HOUR for i in range(7)]
    prices = (100 * np.cumprod([1, 1.01, 1.02, 1.01, 1.03, 1.02, 1.01])).tolist()
    alpha, bars = inputs(values=[0.1, 0.2, 0.1, 0.2, 0.1, 0.2, 0.1], prices=prices, times=times)
    source = replace(gross(), table=table(alpha, bars))
    net = apply_costs(source)
    diagnostic = simulation_diagnostics(net)
    training = feature([start - (10 - i) * HOUR for i in range(6)], [1, 2, 3, 4, 5, 6])
    evaluation_vol = feature(times, [1, 3, 5, 1, 3, 5, 9])
    fitted = fit_volatility_regimes(
        training, calibration_start_us=start - 10 * HOUR, calibration_end_us=start - 4 * HOUR
    )
    evaluation = SplitEvaluation(
        split_window(Split.VALID, interval="1h"),
        "example",
        1,
        alpha_validity(alpha),
        diagnostic,
        net,
        None,
    )
    return (
        evaluation,
        fitness_result(diagnostic),
        stability_report(net, evaluation_vol, fitted),
        cost_sensitivity(source),
    )


def test_crafted_net_series_passes_all_gates_and_negative_series_fails() -> None:
    evaluation, fit, stability, costs = evidence()
    result = evaluate_gates(evaluation, fitness=fit, stability=stability, costs=costs)
    assert result.all_passed and result.base == evaluation.diagnostics.base
    assert result.gate_config_hash == fit.gate_config_hash
    # Reverse the measured sign in the pure comparison control: losing P&L cannot pass.
    failed = decisions(
        sharpe=-result.outcomes[0].value,
        fitness=-fit.value,
        positive_fraction=0,
        cost_stress_sharpe=-result.outcomes[5].value,
    )
    assert {g.gate for g in failed.outcomes if not g.passed} == {"G1", "G2", "G5", "G6"}


def test_invalid_not_rejected_and_missing_evidence_fails_closed() -> None:
    evaluation, fit, stability, costs = evidence()
    invalid = replace(
        evaluation,
        validity=replace(
            evaluation.validity, status="INVALID", reasons=(InvalidReason.CONSTANT_ALPHA,)
        ),
        diagnostics=None,
        simulation=None,
    )
    result = evaluate_gates(invalid)
    assert result.status == "INVALID" and result.invalid_reasons == (InvalidReason.CONSTANT_ALPHA,)
    assert all(g.reason == "invalid_alpha" and not g.passed for g in result.outcomes)
    missing = evaluate_gates(evaluation)
    assert {g.gate for g in missing.outcomes if not g.passed} == {"G2", "G5", "G6"}
    undefined = evaluate_gates(
        evaluation, fitness=fit, stability=replace(stability, n_defined_months=1), costs=costs
    )
    assert not undefined.outcomes[4].passed


def test_mixed_lineage_or_gate_settings_refused() -> None:
    evaluation, fit, stability, costs = evidence()
    for kwargs in (
        {"fitness": replace(fit, gate_config_hash="wrong")},
        {"stability": replace(stability, base=replace(stability.base, snapshot_id="different"))},
        {"costs": replace(costs, base_fees_hash="wrong")},
    ):
        with pytest.raises(SimulationError, match="mismatch"):
            evaluate_gates(evaluation, **kwargs)
    with pytest.raises(SimulationError, match="reservation"):
        evaluate_gates(replace(evaluation, window=split_window(Split.TEST, interval="1h")))


def test_selected_cost_multiplier_is_used_and_absent_point_fails() -> None:
    evaluation, _, stability, _ = evidence()
    gates = load_gates().model_copy(update={"cost_stress_multiplier": 3.0})
    costs = cost_sensitivity(evaluation.simulation.gross)
    result = evaluate_gates(
        evaluation,
        fitness=fitness_result(evaluation.diagnostics, gates=gates),
        stability=stability,
        costs=costs,
        gates=gates,
    )
    assert result.outcomes[5].value == costs.points[3].metrics.metrics.annual_sharpe
    missing = cost_sensitivity(
        evaluation.simulation.gross, config=CostSweepConfig(multipliers=(0.5, 1, 2, 4, 5))
    )
    assert not evaluate_gates(evaluation, costs=missing, gates=gates).outcomes[5].passed
    with pytest.raises(SimulationError, match="finite"):
        decisions(gates=gates.model_copy(update={"sharpe_min": np.inf}))


def test_declared_split_must_match_actual_simulation_and_fitness_value() -> None:
    evaluation, fit, _, _ = evidence()
    with pytest.raises(SimulationError, match="outside"):
        evaluate_gates(replace(evaluation, window=split_window(Split.TRAIN, interval="1h")))
    with pytest.raises(SimulationError, match="Fitness"):
        evaluate_gates(evaluation, fitness=replace(fit, value=999999.0))
    evaluation.simulation.table.loc[evaluation.simulation.table.index[-1], "net_return"] += 0.1
    with pytest.raises(SimulationError, match="diagnostics"):
        evaluate_gates(evaluation)
