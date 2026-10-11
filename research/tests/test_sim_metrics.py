"""Known arithmetic results, boundary costs, horizon scaling and unavailable data."""

import json
from dataclasses import FrozenInstanceError, replace
from math import sqrt

import numpy as np
import pandas as pd
import pytest
from test_sim_costs import gross

from helios.common.config import config_hash
from helios.common.project_config import HorizonFamily, load_splits
from helios.sim.costs import apply_costs
from helios.sim.metrics import return_metrics, simulation_metrics
from helios.sim.positions import SimulationError


def test_known_series_uses_arithmetic_return_sample_volatility_and_zero_risk_free() -> None:
    values = np.array([0.01, -0.02, 0.03, 0.01])
    original = values.copy()
    result = return_metrics(values, periods_per_year=4)
    assert result.n_periods == 4
    assert result.total_return == pytest.approx(0.03)
    assert result.mean_return == pytest.approx(0.0075)
    assert result.annual_return == pytest.approx(0.03)
    variance = 0.000425  # sum of squared deviations 0.001275 / (4 - 1)
    assert result.period_volatility == pytest.approx(sqrt(variance))
    assert result.annual_volatility == pytest.approx(2 * sqrt(variance))
    assert result.per_period_sharpe == pytest.approx(0.0075 / sqrt(variance))
    assert result.annual_sharpe == pytest.approx(0.015 / sqrt(variance))
    np.testing.assert_array_equal(values, original)
    with pytest.raises(FrozenInstanceError):
        result.total_return = 1  # type: ignore[misc]


@pytest.mark.parametrize("value", [0.0, 0.1, -0.1])
def test_constant_returns_have_zero_volatility_and_undefined_sharpe(value: float) -> None:
    result = return_metrics([value] * 3, periods_per_year=8760)
    assert result.period_volatility == result.annual_volatility == 0
    assert result.per_period_sharpe is None and result.annual_sharpe is None
    assert result.annual_return == pytest.approx(value * 8760)


def test_one_observation_and_negative_mean() -> None:
    single = return_metrics([-0.02], periods_per_year=8760)
    assert single.n_periods == 1 and single.annual_return == pytest.approx(-175.2)
    assert single.period_volatility is None and single.annual_sharpe is None
    loser = return_metrics([-0.01, -0.02, 0.0], periods_per_year=8760)
    assert loser.per_period_sharpe == pytest.approx(-1)
    assert loser.annual_sharpe == pytest.approx(-sqrt(8760))


def test_tiny_returns_do_not_underflow_variance_to_false_zero() -> None:
    small = return_metrics([1e-200, 2e-200, 3e-200], periods_per_year=4)
    assert small.period_volatility == pytest.approx(1e-200, rel=1e-12, abs=0)
    assert small.per_period_sharpe == pytest.approx(2)


@pytest.mark.parametrize("values", [[], [[0.1]], [True], ["0.1"], [1j], [np.nan], [np.inf]])
def test_invalid_returns_are_not_silently_coerced_or_removed(values: list[object]) -> None:
    with pytest.raises(SimulationError):
        return_metrics(values, periods_per_year=8760)


@pytest.mark.parametrize("periods", [0, -1, True, 4.0])
def test_invalid_annualization_rejected(periods: int) -> None:
    with pytest.raises(SimulationError, match="positive integer"):
        return_metrics([0.1, 0.2], periods_per_year=periods)


@pytest.mark.parametrize("values,periods", [([1e308, 1e308], 1), ([1e308], 8760)])
def test_overflow_is_an_error(values: list[float], periods: int) -> None:
    with pytest.raises(SimulationError, match="overflow"):
        return_metrics(values, periods_per_year=periods)


def test_simulation_includes_entry_fee_without_an_extra_observation_and_preserves_lineage() -> None:
    net = apply_costs(replace(gross(), snapshot_id="actual-snapshot"))
    original = net.table.copy(deep=True)
    result = simulation_metrics(net)
    expected = return_metrics([0.0964, 0.0982, -0.0006, -0.0012], periods_per_year=8760)
    assert result.metrics.n_periods == 4  # five rows, but the first is an accounting boundary
    assert result.metrics.total_return == pytest.approx(0.1928)
    assert result.metrics.annual_return == pytest.approx(expected.annual_return)
    assert result.metrics.period_volatility == pytest.approx(expected.period_volatility)
    assert result.metrics.annual_sharpe == pytest.approx(expected.annual_sharpe)
    assert result.config.horizon_family == HorizonFamily.HOURLY
    assert result.config.periods_per_year == 8760
    assert result.config_hash == config_hash(result.config)
    assert (
        json.loads(result.config_json)["boundary_convention"] == "entry_cost_in_first_interval_v1"
    )
    assert result.splits_hash == config_hash(load_splits())
    assert result.experiment_id == 1 and result.snapshot_id == "actual-snapshot"
    assert result.position_config_hash == "config" and result.fees_hash == net.fees_hash
    assert result.code_commit == "commit" and result.dirty
    pd.testing.assert_frame_equal(net.table, original)
    net.table["net_return"] = 9.0
    assert result.metrics.total_return == pytest.approx(0.1928)


def test_minute_scaling_and_explicit_configuration_snapshot() -> None:
    source = gross()
    minute = replace(source, config=source.config.model_copy(update={"interval": "1m"}))
    minute.table["open_time"] = minute.table.open_time // 60
    net = apply_costs(minute)
    settings = load_splits()
    result = simulation_metrics(net, splits=settings)
    assert result.config.horizon_family == HorizonFamily.MINUTE
    assert result.config.periods_per_year == 525600
    assert result.metrics.annual_return == pytest.approx(0.1928 / 4 * 525600)
    settings.families[HorizonFamily.MINUTE] = settings.families[HorizonFamily.HOURLY]
    assert result.config.periods_per_year == 525600
    del settings.families[HorizonFamily.MINUTE]
    with pytest.raises(SimulationError, match="configured"):
        simulation_metrics(net, splits=settings)


def test_lone_boundary_has_total_entry_expense_but_no_period_metrics() -> None:
    net = apply_costs(gross())
    net = replace(net, table=net.table.iloc[:1].copy())
    result = simulation_metrics(net).metrics
    assert result.n_periods == 0 and result.total_return == pytest.approx(-0.0012)
    assert result.mean_return is result.annual_return is result.period_volatility is None
    assert result.annual_volatility is result.per_period_sharpe is result.annual_sharpe is None


@pytest.mark.parametrize(
    "change",
    ["unknown", "gap", "duplicate", "off_grid", "boundary", "mask", "nan", "text", "empty"],
)
def test_incomplete_or_corrupt_simulation_is_rejected(change: str) -> None:
    net = apply_costs(gross())
    index = net.table.index
    if change == "unknown":
        net.table.loc[index[1], ["net_return", "net_available"]] = [np.nan, False]
    elif change == "gap":
        net = replace(net, table=net.table.drop(index[1]))
    elif change == "duplicate":
        net.table.loc[index[1], "open_time"] = net.table.open_time.iloc[0]
    elif change == "off_grid":
        net.table["open_time"] += 1
    elif change == "boundary":
        net.table.loc[index[1], "initial_boundary"] = True
    elif change == "mask":
        net.table["net_available"] = 1
    elif change == "nan":
        net.table.loc[index[1], "net_return"] = np.inf
    elif change == "text":
        net.table["net_return"] = "0.1"
    elif change == "empty":
        net = replace(net, table=net.table.iloc[:0])
    with pytest.raises(SimulationError):
        simulation_metrics(net)


def test_unimplemented_horizon_family_is_not_guessed() -> None:
    source = gross()
    source = replace(source, config=source.config.model_copy(update={"interval": "1s"}))
    with pytest.raises(SimulationError, match="configured"):
        simulation_metrics(apply_costs(source))
