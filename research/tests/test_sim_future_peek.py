"""SIM-015: intentionally impossible forecasts test the return alignment only."""

from math import sqrt

import numpy as np
import pandas as pd
import pytest
from sim_controls import N_PERIODS, market_returns, run_control

from helios.alpha.evaluator import AlphaSeries
from helios.sim.validity import alpha_validity

pytestmark = pytest.mark.leakage


def test_next_return_alpha_has_exact_squared_pnl_and_implausible_sharpe() -> None:
    returns = market_returns()
    # alpha[t] = close[t+1]/close[t]-1. Deliberately illegal information.
    # The last decision is explicitly flat; no next-return label is invented there.
    values = np.r_[returns, 0.0]
    net, summary = run_control(values, returns)
    np.testing.assert_allclose(net.table.gross_return.iloc[1:], returns**2, rtol=1e-10, atol=1e-17)
    assert (net.table.gross_return.iloc[1:] > 0).all()
    assert summary.metrics.n_periods == N_PERIODS
    assert summary.metrics.annual_sharpe > 50
    expected = np.mean(returns**2) / np.std(returns**2, ddof=1) * sqrt(8760)
    assert np.isclose(summary.metrics.annual_sharpe, expected)
    print(f"Synthetic illegal next-return annual Sharpe={summary.metrics.annual_sharpe:.8f}")


def test_delaying_peek_one_extra_bar_removes_the_artificial_advantage() -> None:
    returns = market_returns()
    _, peek = run_control(np.r_[returns, 0.0], returns)
    delayed_net, delayed = run_control(np.r_[returns, 0.0], returns, lag=2)
    np.testing.assert_allclose(
        delayed_net.table.gross_return.iloc[2:], returns[:-1] * returns[1:], rtol=1e-10, atol=1e-17
    )
    assert delayed_net.table.gross_return.iloc[1] == 0
    assert abs(delayed.metrics.annual_sharpe) < 3 * sqrt(8760 / N_PERIODS)
    assert peek.metrics.annual_sharpe > 20 * max(1, abs(delayed.metrics.annual_sharpe))
    print(f"Synthetic delayed-control annual Sharpe={delayed.metrics.annual_sharpe:.8f}")


def test_opposite_peek_is_an_exact_losing_control() -> None:
    returns = market_returns()
    net, summary = run_control(np.r_[-returns, 0.0], returns)
    np.testing.assert_allclose(
        net.table.gross_return.iloc[1:], -(returns**2), rtol=1e-10, atol=1e-17
    )
    assert summary.metrics.annual_sharpe < -50


def test_final_decision_cannot_change_the_return_already_earned() -> None:
    returns = market_returns()
    original, _ = run_control(np.r_[returns, 0.0], returns)
    changed, _ = run_control(np.r_[returns, 1.0], returns)
    np.testing.assert_array_equal(original.table.gross_return, changed.table.gross_return)
    # This is a varying synthetic control, not a constant/degenerate alpha.
    alpha = AlphaSeries(
        "BTCUSDT",
        original.table.open_time,
        pd.Series(np.r_[returns, 0.0]),
        pd.Series(True, index=original.table.index),
    )
    assert alpha_validity(alpha).valid
