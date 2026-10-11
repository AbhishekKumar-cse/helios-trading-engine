"""The four accepted ADR examples, undefined metrics and recorded constants."""

import json
from dataclasses import replace

import numpy as np
import pytest
from test_sim_costs import gross

from helios.common.config import config_hash
from helios.common.project_config import load_gates
from helios.sim.costs import apply_costs
from helios.sim.diagnostics import simulation_diagnostics
from helios.sim.fitness import fitness, fitness_result
from helios.sim.positions import SimulationError


@pytest.mark.parametrize(
    "sharpe,annual,turnover,expected",
    [
        (1.5, 0.12, 0.30, 0.9486832980505138),
        (1.2, 0.20, 0.15, 1.3856406460551018),
        (1.5, 0.12, 0.05, 1.469693845669907),
        (-0.8, -0.10, 0.20, -0.5656854249492381),
    ],
)
def test_four_adr_examples(sharpe: float, annual: float, turnover: float, expected: float) -> None:
    assert fitness(sharpe, annual, turnover) == pytest.approx(expected)


def test_floor_prevents_zero_turnover_blowup_and_preserves_sign() -> None:
    assert fitness(1.5, 0.12, 0) == fitness(1.5, 0.12, 0.05)
    assert fitness(-1.5, -0.12, 0) == pytest.approx(-1.469693845669907)
    assert fitness(1.5, 0.0, 0) == 0
    assert fitness(None, 0.0, 0) is None
    assert fitness(1.0, None, 0) is None
    assert fitness(1.0, 0.12, None) is None


@pytest.mark.parametrize(
    "values",
    [
        (np.inf, 0.12, 0.3, 0.125),
        (1.0, np.nan, 0.3, 0.125),
        (1.0, 0.12, -0.3, 0.125),
        (1.0, 0.12, np.nan, 0.125),
        (1.0, 0.12, 0.3, 0.0),
        (1.0, 0.12, 0.3, np.inf),
        (True, 0.12, 0.3, 0.125),
        (1e308, 1e308, 0, 0.125),
    ],
)
def test_bad_values_refused(values: tuple[float, float, float, float]) -> None:
    with pytest.raises(SimulationError):
        fitness(*values[:3], floor=values[3])


def test_wrapper_uses_configured_floor_and_keeps_lineage() -> None:
    diagnostics = simulation_diagnostics(apply_costs(gross()))
    gates = load_gates()
    result = fitness_result(diagnostics, gates=gates)
    assert result.diagnostics is diagnostics
    assert result.value == fitness(
        diagnostics.base.metrics.annual_sharpe,
        diagnostics.base.metrics.annual_return,
        diagnostics.mean_turnover,
    )
    assert result.denominator == 1.5
    assert result.gate_config_hash == config_hash(gates)
    assert json.loads(result.config_json)["turnover_floor"] == 0.125
    changed = fitness_result(
        diagnostics, gates=gates.model_copy(update={"fitness_turnover_floor": 2.0})
    )
    assert changed.denominator == 2.0 and changed.config_hash != result.config_hash
    assert changed.gate_config_hash != result.gate_config_hash
    empty = replace(diagnostics, mean_turnover=None)
    assert fitness_result(empty).value is None
