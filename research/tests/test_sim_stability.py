"""Known monthly moments, earlier calibration and start-of-interval regime labels."""

from dataclasses import replace
from math import sqrt

import numpy as np
import pandas as pd
import pytest
from test_sim_costs import gross
from test_sim_positions import inputs, table

from helios.features.runner import FeatureFrame
from helios.sim.costs import NetSimulation, apply_costs
from helios.sim.positions import SimulationError
from helios.sim.stability import fit_volatility_regimes, stability_report

HOUR = 3_600_000_000


def feature(times: list[int], values: list[float], mask: list[bool] | None = None) -> FeatureFrame:
    return FeatureFrame(
        "BTCUSDT",
        pd.Series(times),
        pd.DataFrame({"volatility_24": values}),
        pd.DataFrame({"volatility_24": [True] * len(values) if mask is None else mask}),
    )


def fixture() -> tuple[NetSimulation, FeatureFrame, FeatureFrame]:
    start = int(pd.Timestamp("2026-01-31T21:00:00Z").value // 1000)
    prices = [100.0]
    for value in [0.02, 0.01, -0.03, -0.01, 0.02, -0.01]:
        prices.append(prices[-1] * (1 + value))
    times = [start + i * HOUR for i in range(7)]
    alpha, bars = inputs(values=[1.0] * 7, prices=prices, times=times)
    net = apply_costs(replace(gross(), table=table(alpha, bars)))
    training = feature([start - (10 - i) * HOUR for i in range(6)], [1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    evaluation = feature(times, [1.0, 3.0, 5.0, 1.0, 3.0, 5.0, 99.0])
    return net, training, evaluation


def fit(training: FeatureFrame):
    return fit_volatility_regimes(
        training,
        calibration_start_us=int(training.open_time.iloc[0]),
        calibration_end_us=int(training.open_time.iloc[-1]) + HOUR,
    )


def test_hand_calculated_monthly_summary_and_regime_contributions() -> None:
    net, training, evaluation = fixture()
    fitted = fit(training)
    result = stability_report(net, evaluation, fitted)
    assert [m.month for m in result.months] == ["2026-01", "2026-02"]
    january = 0.0144 / (0.0088 / sqrt(2)) * sqrt(8760)
    february = -0.0075 / sqrt(0.000425) * sqrt(8760)
    assert result.months[0].metrics.annual_sharpe == pytest.approx(january)
    assert result.months[1].metrics.annual_sharpe == pytest.approx(february)
    assert result.mean_monthly_sharpe == pytest.approx((january + february) / 2)
    assert result.min_monthly_sharpe == pytest.approx(february)
    assert result.positive_month_fraction == 0.5 and result.n_defined_months == 2
    assert [m.metrics.n_periods for m in result.months] == [2, 4]
    assert [m.expected_periods for m in result.months] == [31 * 24, 28 * 24]
    assert all(m.has_gaps for m in result.months)
    assert [r.n_periods for r in result.regimes] == [2, 2, 2]
    assert result.n_unavailable_regime == 0
    assert sum(
        r.metrics.total_return for r in result.regimes if r.metrics is not None
    ) == pytest.approx(result.base.metrics.total_return)
    assert sum(m.metrics.total_return for m in result.months) == pytest.approx(-0.0012)
    assert fitted.lower_cut == pytest.approx(8 / 3) and fitted.upper_cut == pytest.approx(13 / 3)
    assert fitted.n_rows == fitted.n_available == 6


def test_later_volatility_changes_cannot_relabel_earlier_return_intervals() -> None:
    net, training, evaluation = fixture()
    fitted = fit(training)
    original = stability_report(net, evaluation, fitted)
    evaluation.values.iloc[-1, 0] = (
        100000.0  # ending feature cannot classify the last held interval
    )
    changed = stability_report(net, evaluation, fitted)
    assert changed.regimes == original.regimes
    assert changed.evaluation_volatility_hash != original.evaluation_volatility_hash
    # Appending future observations cannot affect the explicitly earlier fit.
    later_times = training.open_time.tolist() + evaluation.open_time.tolist()
    later_values = training.values.volatility_24.tolist() + evaluation.values.volatility_24.tolist()
    extended = feature(later_times, later_values)
    assert (
        fit_volatility_regimes(
            extended,
            calibration_start_us=fitted.calibration_start_us,
            calibration_end_us=fitted.calibration_end_us,
        )
        == fitted
    )


def test_unknown_regime_is_counted_and_threshold_ties_are_deterministic() -> None:
    net, training, evaluation = fixture()
    fitted = fit(training)
    evaluation.available.iloc[1, 0] = False
    evaluation.values.iloc[1, 0] = np.nan
    result = stability_report(net, evaluation, fitted)
    assert result.n_unavailable_regime == 1
    assert sum(r.n_periods for r in result.regimes) == 5
    evaluation.values.iloc[0, 0] = fitted.lower_cut
    evaluation.values.iloc[2, 0] = fitted.upper_cut
    tied = stability_report(net, evaluation, fitted)
    assert [r.n_periods for r in tied.regimes] == [2, 2, 1]


def test_future_or_overlapping_calibration_rejected() -> None:
    net, training, evaluation = fixture()
    fitted = replace(fit(training), calibration_end_us=int(net.table.open_time.iloc[0]) + HOUR)
    with pytest.raises(SimulationError, match="before"):
        stability_report(net, evaluation, fitted)


@pytest.mark.parametrize("values", [[1.0, 1.0, 1.0], [1.0, 2.0], [0.0] * 8 + [1.0, 2.0]])
def test_degenerate_or_insufficient_terciles_not_invented(values: list[float]) -> None:
    training = feature([i * HOUR for i in range(len(values))], values)
    with pytest.raises(SimulationError):
        fit_volatility_regimes(
            training, calibration_start_us=0, calibration_end_us=len(values) * HOUR
        )


def test_unavailable_calibration_values_and_bad_masks() -> None:
    training = feature(
        [i * HOUR for i in range(5)], [1.0, 2.0, 3.0, np.nan, 99.0], [True, True, True, False, True]
    )
    fitted = fit_volatility_regimes(training, calibration_start_us=0, calibration_end_us=4 * HOUR)
    assert fitted.n_rows == 4 and fitted.n_available == 3
    assert fitted.upper_cut < 3  # later 99 excluded
    training.available["volatility_24"] = 1
    with pytest.raises(SimulationError, match="boolean"):
        fit(training)


def test_no_defined_monthly_sharpe_and_lone_boundary() -> None:
    net, training, evaluation = fixture()
    net.table["net_return"] = 0.0
    result = stability_report(net, evaluation, fit(training))
    assert result.n_defined_months == 0
    assert (
        result.mean_monthly_sharpe
        is result.min_monthly_sharpe
        is result.positive_month_fraction
        is None
    )
    lone = stability_report(
        replace(net, table=net.table.iloc[:1].copy()), evaluation, fit(training)
    )
    assert not lone.months and lone.n_unavailable_regime == 0
    assert all(r.metrics is None and r.n_periods == 0 for r in lone.regimes)


def test_mismatched_symbol_negative_volatility_and_config_lineage_fail() -> None:
    net, training, evaluation = fixture()
    fitted = fit(training)
    with pytest.raises(SimulationError, match="symbol"):
        stability_report(net, replace(evaluation, symbol="OTHER"), fitted)
    with pytest.raises(SimulationError, match="lineage"):
        stability_report(net, evaluation, replace(fitted, config_hash="incorrect"))
    evaluation.values.iloc[0, 0] = -0.01
    with pytest.raises(SimulationError, match="non-negative"):
        stability_report(net, evaluation, fitted)
