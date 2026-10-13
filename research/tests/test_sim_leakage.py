"""BT-031 controls use synthetic data; never real TEST data or invented results."""

import numpy as np
import pandas as pd
import pytest
from sim_controls import N_PERIODS, run_control

from helios.alpha.evaluator import AlphaSeries
from helios.sim.validity import InvalidReason, alpha_validity

pytestmark = pytest.mark.leakage


def test_constant_alpha_is_invalid() -> None:
    alpha = AlphaSeries(
        "BTCUSDT",
        pd.Series(np.arange(100) * 3_600_000_000),
        pd.Series(0.5, index=range(100)),
        pd.Series(True, index=range(100)),
    )
    result = alpha_validity(alpha)
    assert result.status == "INVALID" and result.reasons == (InvalidReason.CONSTANT_ALPHA,)


def test_delaying_a_causal_predictive_feature_degrades_performance() -> None:
    # A predeclared stationary AR(1) fixture makes a causal lag predictive.
    # Degradation is not a universal claim about every real-market feature.
    shocks = np.random.default_rng(111).normal(0, 0.002, N_PERIODS)
    returns = np.empty(N_PERIODS)
    returns[0] = shocks[0]
    for i in range(1, N_PERIODS):
        returns[i] = 0.6 * returns[i - 1] + shocks[i]
    current = np.r_[0.0, np.sign(returns)]
    shifted = np.r_[0.0, 0.0, np.sign(returns[:-1])]
    net, before = run_control(current, returns)
    delayed, after = run_control(shifted, returns)
    np.testing.assert_allclose(net.table.held_position.iloc[2:], np.sign(returns[:-1]))
    np.testing.assert_allclose(delayed.table.held_position.iloc[3:], np.sign(returns[:-2]))
    assert before.metrics.annual_sharpe > 0
    assert after.metrics.annual_sharpe < 0.75 * before.metrics.annual_sharpe
