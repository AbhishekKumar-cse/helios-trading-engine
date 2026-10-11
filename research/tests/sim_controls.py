"""Test-only synthetic controls: no real data, registry claims or TEST access."""

import numpy as np
import pandas as pd

from helios.alpha.evaluator import AlphaSeries
from helios.alpha.output import bound_alpha
from helios.common.config import config_hash
from helios.common.project_config import load_fees
from helios.sim.costs import apply_costs
from helios.sim.metrics import simulation_metrics
from helios.sim.positions import GrossSimulation, PositionConfig, _position_table

N_PERIODS = 20_000
N_SEEDS = 20
MARKET_SEED = 81073


def market_returns(n=N_PERIODS):
    """Independent deterministic synthetic Gaussian returns, never actual observations."""
    return np.random.default_rng(MARKET_SEED).normal(0, 0.005, n)


def run_control(values, returns, *, lag=1, with_costs=False):
    assert len(values) == len(returns) + 1
    times = pd.Series(np.arange(len(values), dtype=np.int64) * 3_600_000_000)
    alpha = bound_alpha(
        AlphaSeries("BTCUSDT", times, pd.Series(values), pd.Series(True, index=times.index))
    )
    bars = pd.DataFrame(
        {"open_time": times, "close": 100 * np.exp(np.r_[0, np.cumsum(np.log1p(returns))])}
    )
    config = PositionConfig(interval="1h", position_scale=1, execution_lag=lag)
    # This private arithmetic fixture is not a registered/public research run.
    source = GrossSimulation(
        "BTCUSDT",
        1,
        config,
        config_hash(config),
        "0" * 40,
        True,
        None,
        _position_table(alpha, bars, config),
    )
    fees = load_fees()
    if not with_costs:
        fees = fees.model_copy(
            update={
                "maker_fee_bps": 0.0,
                "taker_fee_bps": 0.0,
                "slippage_bps": {s: 0.0 for s in fees.slippage_bps},
            }
        )
    net = apply_costs(source, fees)
    return net, simulation_metrics(net)
