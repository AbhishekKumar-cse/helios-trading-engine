"""Hand-calculated entry, flip, exit and unavailable-cost accounting."""

import json
from dataclasses import replace

import numpy as np
import pytest
from pydantic import ValidationError
from sqlalchemy import Connection
from test_sim_positions import inputs, table

from helios.common.project_config import load_fees
from helios.registry.experiments import ExperimentKind, register_experiment
from helios.sim.costs import apply_costs, simulate_net
from helios.sim.positions import GrossSimulation, PositionConfig, SimulationError


def gross() -> GrossSimulation:
    alpha, bars = inputs()
    return GrossSimulation(
        "BTCUSDT",
        1,
        PositionConfig(interval="1h", position_scale=1),
        "config",
        "commit",
        True,
        None,
        table(alpha, bars),
    )


def test_golden_entry_flip_exit_and_lineage() -> None:
    source = gross()
    result = apply_costs(source)
    np.testing.assert_allclose(result.table.cost, [0.0012, 0.0024, 0.0018, 0.0006, 0.0012])
    np.testing.assert_allclose(result.table.net_return, [-0.0012, 0.0976, 0.0982, -0.0006, -0.0012])
    assert result.table.net_available.all()
    assert result.gross is source and len(result.fees_hash) == 64
    assert json.loads(result.fees_json)["version"] == "fees_v1"
    assert "cost" not in source.table
    result.table.loc[result.table.index[0], "position"] = 0
    assert source.table.position.iloc[0] == 1


def test_public_net_entry_point_preserves_registered_experiment(connection: Connection) -> None:
    experiment = register_experiment(
        connection,
        kind=ExperimentKind.BACKTEST,
        hypothesis="Synthetic cost accounting verification",
        params={},
        author="test",
    )
    alpha, bars = inputs()
    result = simulate_net(
        connection,
        experiment_id=experiment.experiment_id,
        alpha=alpha,
        bars=bars,
        interval="1h",
    )
    assert result.gross.experiment_id == experiment.experiment_id
    np.testing.assert_allclose(result.table.net_return, [-0.0012, 0.0976, 0.0982, -0.0006, -0.0012])


def test_slippage_by_symbol_and_maker_not_used() -> None:
    fees = load_fees().model_copy(update={"maker_fee_bps": 900})
    assert apply_costs(gross(), fees).cost_bps == 12
    assert apply_costs(replace(gross(), symbol="SOLUSDT"), fees).cost_bps == 15
    with pytest.raises(KeyError, match="no slippage"):
        apply_costs(replace(gross(), symbol="UNKNOWN"), fees)


def test_flat_zero_fees_and_frozen_fee_snapshot() -> None:
    source = gross()
    source.table["turnover"] = 0.0
    fees = load_fees()
    result = apply_costs(source, fees)
    fees.slippage_bps["BTCUSDT"] = 100
    assert result.cost_bps == 12
    assert json.loads(result.fees_json)["slippage_bps"]["BTCUSDT"] == 2
    assert (result.table.cost == 0).all()
    np.testing.assert_array_equal(result.table.net_return, source.table.gross_return)


def test_unknown_cost_or_return_is_not_zero_filled() -> None:
    source = gross()
    source.table.loc[source.table.index[1], ["turnover", "turnover_available"]] = [np.nan, False]
    source.table.loc[source.table.index[2], ["gross_return", "gross_available"]] = [np.nan, False]
    result = apply_costs(source).table
    assert np.isnan(result.cost.iloc[1]) and not result.cost_available.iloc[1]
    assert result.cost_available.iloc[2] and np.isnan(result.net_return.iloc[2])
    assert result.net_available.tolist() == [True, False, False, True, True]


@pytest.mark.parametrize("value", [-1.0, np.inf, np.nan])
def test_invalid_available_turnover_rejected(value: float) -> None:
    source = gross()
    source.table.loc[source.table.index[0], "turnover"] = value
    with pytest.raises(SimulationError, match="turnover"):
        apply_costs(source)


@pytest.mark.parametrize("field", ["maker_fee_bps", "taker_fee_bps", "slippage_bps"])
@pytest.mark.parametrize("value", [np.inf, np.nan])
def test_nonfinite_fee_rejected_even_after_nested_mutation(field: str, value: float) -> None:
    update = {field: {"BTCUSDT": value} if field == "slippage_bps" else value}
    with pytest.raises(ValidationError):
        apply_costs(gross(), load_fees().model_copy(update=update))
