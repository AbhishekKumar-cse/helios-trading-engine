"""UTC daily aggregation, initial costs, reference drawdowns and directional hits."""

from dataclasses import replace
from math import sqrt

import numpy as np
import pandas as pd
import pytest
from test_sim_costs import gross

from helios.sim.costs import apply_costs
from helios.sim.diagnostics import DAY_US, daily_metrics, pnl_drawdown, simulation_diagnostics
from helios.sim.positions import SimulationError

HOUR = DAY_US // 24


def test_daily_30_day_golden_and_hour_minute_invariance() -> None:
    daily = np.array([0.01, -0.02, 0.03] * 10)
    for interval, count, period in (("1h", 24, HOUR), ("1m", 1440, HOUR // 60)):
        values = np.repeat(daily / count, count)
        result = daily_metrics(
            pd.Series(np.arange(len(values)) * period), pd.Series(values), interval=interval
        )
        assert result.n_days == 30
        assert result.sharpe == pytest.approx(daily.mean() / daily.std(ddof=1) * sqrt(365))
        assert all(not day.has_gaps for day in result.days)
        np.testing.assert_allclose([day.net_return for day in result.days], daily)


def test_absent_days_not_filled_and_partial_days_flagged() -> None:
    result = daily_metrics(
        pd.Series([0, HOUR, 2 * DAY_US]), pd.Series([0.1, -0.02, 0.03]), interval="1h"
    )
    assert [day.day for day in result.days] == ["1970-01-01", "1970-01-03"]
    assert [day.n_periods for day in result.days] == [2, 1]
    assert all(day.has_gaps for day in result.days)
    assert result.days[0].net_return == pytest.approx(0.08)
    assert result.sharpe is None and "30" in str(result.unavailable_reason)


def test_zero_daily_variance_and_too_few_days() -> None:
    for days in (29, 30):
        result = daily_metrics(
            pd.Series(np.arange(days) * DAY_US), pd.Series(np.zeros(days)), interval="1h"
        )
        assert result.sharpe is None
        assert result.unavailable_reason == (
            "zero daily variance" if days == 30 else "fewer than 30 observed UTC days"
        )


def test_drawdown_recovery_and_unrecovered_duration() -> None:
    # Initial entry loss; peak +0.09, trough +0.04, recovery +0.11, unfinished loss.
    values = [-0.01, 0.10, -0.03, -0.02, 0.07, -0.04]
    result = pnl_drawdown(pd.Series(np.arange(6) * HOUR), pd.Series(values), interval="1h")
    assert result.magnitude == pytest.approx(0.05)
    assert result.duration_periods == 3  # peak at 1 through recovery at 4
    assert result.duration_us == 3 * HOUR
    declining = pnl_drawdown(
        pd.Series(np.arange(3) * HOUR), pd.Series([-0.01, -0.02, -0.03]), interval="1h"
    )
    assert declining.magnitude == pytest.approx(0.06) and declining.duration_periods == 2


def test_simulation_golden_hit_rate_turnover_and_boundary_cost() -> None:
    net = apply_costs(gross())
    original = net.table.copy(deep=True)
    result = simulation_diagnostics(net)
    assert result.total_turnover == 6 and result.mean_turnover == 1.5
    assert result.base.metrics.n_periods == 4 and result.n_hit_periods == 4
    assert result.hit_rate == 0.5  # +/+ and -/-; +/0 and 0/+ do not match
    assert result.daily.days[0].net_return == pytest.approx(0.1928)
    assert result.drawdown.magnitude == pytest.approx(0.0018)
    assert result.drawdown.duration_periods == 2
    pd.testing.assert_frame_equal(net.table, original)
    lone = simulation_diagnostics(replace(net, table=net.table.iloc[:1].copy()))
    assert lone.mean_turnover is None and lone.total_turnover == 1
    assert lone.daily.n_days == 0 and lone.hit_rate is None
    assert lone.drawdown.magnitude == pytest.approx(0.0012)


def test_hit_rate_is_not_profitability_and_unknown_market_is_explicit() -> None:
    net = apply_costs(gross())
    net.table["period_return"] = 0.0
    net.table["held_position"] = 0.0
    assert simulation_diagnostics(net).hit_rate == 1.0  # sign(0) == sign(0), per spec
    net.table.loc[net.table.index[2], ["period_return", "return_available"]] = [np.nan, False]
    result = simulation_diagnostics(net)
    assert result.hit_rate is None and result.n_hit_periods == 3


@pytest.mark.parametrize("kind", ["duplicate", "off_grid", "nonfinite", "text"])
def test_invalid_daily_input(kind: str) -> None:
    times, values = pd.Series([0, HOUR]), pd.Series([0.01, 0.02])
    if kind == "duplicate":
        times.iloc[1] = 0
    elif kind == "off_grid":
        times.iloc[1] += 1
    elif kind == "nonfinite":
        values.iloc[1] = np.inf
    else:
        values = pd.Series(["1", "2"])
    with pytest.raises(SimulationError):
        daily_metrics(times, values, interval="1h")


def test_unknown_turnover_and_drawdown_gaps_fail() -> None:
    net = apply_costs(gross())
    net.table.loc[net.table.index[1], "turnover_available"] = False
    with pytest.raises(SimulationError, match="turnover"):
        simulation_diagnostics(net)
    with pytest.raises(SimulationError, match="contiguous"):
        pnl_drawdown(pd.Series([0, 2 * HOUR]), pd.Series([0.1, -0.2]), interval="1h")
