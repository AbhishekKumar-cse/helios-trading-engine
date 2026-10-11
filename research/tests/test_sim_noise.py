"""SIM-014: deterministic 20-seed zero-cost null and cost-drag controls."""

from math import sqrt

import numpy as np
from sim_controls import N_PERIODS, N_SEEDS, market_returns, run_control


def test_twenty_noise_seeds_have_mean_sharpe_consistent_with_zero() -> None:
    returns = market_returns()
    sharpes = []
    for seed in range(N_SEEDS):
        # Independent generator: never seed signals from the market generator.
        values = np.random.default_rng(seed).uniform(-1, 1, N_PERIODS + 1)
        net, summary = run_control(values, returns)
        assert summary.metrics.n_periods == N_PERIODS
        assert (net.table.cost == 0).all()
        assert summary.metrics.annual_sharpe is not None
        sharpes.append(summary.metrics.annual_sharpe)
    mean = float(np.mean(sharpes))
    # A priori null SE: annualized Sharpe / sqrt(period count * seed count).
    null_se = sqrt(8760 / (N_PERIODS * N_SEEDS))
    assert abs(mean) < 3 * null_se, (mean, null_se)
    # Also check the uncertainty estimated across all seeds, without cherry-picking.
    observed_se = float(np.std(sharpes, ddof=1)) / sqrt(N_SEEDS)
    assert abs(mean) < 3 * observed_se, (mean, observed_se)
    print(
        f"Synthetic 20-seed zero-cost mean annual Sharpe={mean:.8f}; "
        f"null SE={null_se:.8f}; observed SE={observed_se:.8f}"
    )


def test_noise_cost_drag_is_not_mistaken_for_alignment_failure() -> None:
    returns = market_returns()
    gross_means, net_means = [], []
    for seed in range(N_SEEDS):
        values = np.random.default_rng(seed).uniform(-1, 1, N_PERIODS + 1)
        net, summary = run_control(values, returns, with_costs=True)
        assert summary.metrics.n_periods == N_PERIODS
        assert float(net.table.cost.sum()) > 0
        assert summary.metrics.total_return < float(net.table.gross_return.sum())
        gross_means.append(float(net.table.gross_return.iloc[1:].mean()))
        net_means.append(summary.metrics.mean_return)
    assert np.mean(net_means) < np.mean(gross_means)
    assert np.mean(net_means) < 0
