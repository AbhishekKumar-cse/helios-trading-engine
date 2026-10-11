"""Exact five-point gross-minus-cost curve and stable input/source configuration."""

import json

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError
from test_sim_costs import gross

from helios.common.config import config_hash
from helios.common.project_config import load_fees
from helios.sim.cost_sensitivity import CostSweepConfig, cost_sensitivity
from helios.sim.positions import SimulationError


def test_known_five_point_curve_keeps_gross_execution_and_lineage() -> None:
    source, fees = gross(), load_fees()
    original = source.table.copy(deep=True)
    result = cost_sensitivity(source, fees=fees)
    assert [p.multiplier for p in result.points] == [0.5, 1, 2, 3, 4]
    assert [p.cost_bps for p in result.points] == [6, 12, 24, 36, 48]
    np.testing.assert_allclose(
        [p.total_cost for p in result.points], [0.0036, 0.0072, 0.0144, 0.0216, 0.0288]
    )
    np.testing.assert_allclose(
        [p.metrics.metrics.total_return for p in result.points],
        [0.1964, 0.1928, 0.1856, 0.1784, 0.1712],
    )
    assert result.cost_stress_sharpe == result.points[2].metrics.metrics.annual_sharpe
    assert result.base_fees_hash == config_hash(fees)
    assert result.points[1].metrics.fees_hash == result.base_fees_hash
    assert len({p.metrics.fees_hash for p in result.points}) == 5
    assert all(
        p.metrics.experiment_id == source.experiment_id and p.metrics.code_commit == "commit"
        for p in result.points
    )
    assert all(p.metrics.metrics.n_periods == 4 for p in result.points)
    pd.testing.assert_frame_equal(source.table, original)
    fees.slippage_bps["BTCUSDT"] = 900
    assert json.loads(result.base_fees_json)["slippage_bps"]["BTCUSDT"] == 2


def test_zero_turnover_costs_and_undefined_sharpe_are_not_fabricated() -> None:
    source = gross()
    source.table["turnover"] = 0.0
    source.table["gross_return"] = 0.0
    result = cost_sensitivity(source)
    assert all(p.total_cost == 0 and p.metrics.metrics.total_return == 0 for p in result.points)
    assert result.cost_stress_sharpe is None


@pytest.mark.parametrize(
    "values",
    [
        (1, 2, 3, 4),
        (0, 1, 2, 3, 4),
        (True, 1, 2, 3, 4),
        (0.5, 1, 1, 3, 4),
        (4, 3, 2, 1, 0.5),
        (0.5, 1, 2, 3, np.inf),
    ],
)
def test_invalid_sweep_config(values: tuple[float, ...]) -> None:
    with pytest.raises(ValidationError):
        CostSweepConfig(multipliers=values)


def test_unknown_net_data_cannot_be_hidden_by_cost_sweep() -> None:
    source = gross()
    source.table.loc[source.table.index[1], "gross_available"] = False
    with pytest.raises(SimulationError, match="availability"):
        cost_sensitivity(source)
