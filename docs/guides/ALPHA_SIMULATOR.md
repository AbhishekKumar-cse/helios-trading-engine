# Lagged positions and gross returns (step 095)

`helios.sim.positions.simulate_gross` accepts one coin's bounded alpha, its bars,
an explicit interval and an execution lag of at least one decision interval.
It verifies a real open preregistered experiment through the caller's PostgreSQL
connection before computation. No result, experiment, promotion or trade is created
by the simulator. Costs/net returns and basic metrics are described below; split
access, persisted results and gates remain later steps.

```python
from helios.alpha.output import evaluate_definition
from helios.common.db import get_engine
from helios.registry.experiments import register_experiment
from helios.sim.positions import simulate_gross

with get_engine().begin() as connection:
    experiment = register_experiment(
        connection,
        hypothesis="B0 beats a flat comparison on hourly validation after costs",
        params={"baseline": "baseline_b0@1", "interval": "1h", "execution_lag": 1},
        author="researcher",
    )  # record the actual question/settings before observing results
    alpha = evaluate_definition(idea, features, interval="1h")
    gross = simulate_gross(
        connection, experiment_id=experiment.experiment_id, alpha=alpha,
        bars=bars, interval="1h", execution_lag=1,
    )
```

The example expects a loaded definition `idea`, a causal `FeatureFrame` named
`features`, and that coin's chronological bars. Real studies must attach the actual
registered data snapshot to the experiment. Missing snapshot metadata remains null,
never invented. This computation does not authorize TEST access or produce a
reportable full evaluation; the split/access and result pipelines are separate.

## Timing and units

`target_position_t = clip(alpha_t / position_scale, -1, 1)`, using the definition's
stored positive scale. The alpha must already carry the final output convention.
Default lag 1 schedules this target after the current bar close, and earns the next
interval's return. With lag k, scheduled position t is target t-(k-1), and held
position for interval t is scheduled position t-1. Zero/negative/fractional lags
are rejected. The initial exposure is explicitly flat through startup/warm-up until
the first usable scheduled target; first entry is charged turnover from that flat state.

`period_return_t = close_t / close_(t-1) - 1` is a **simple** fractional return
ending at row t. It is the forward interval associated with decision t-1. Gross
return t uses **held_position_t**, never target t from the ending bar. Returns are
not shifted a second time, and log-return features are not substituted for portfolio
simple returns. `open_time` identifies each bar; the close and feature values become
known after that bar completes. This is a reference exposure calculation, not a
simulation of order-book fills or executable spot short-selling.

Turnover t is `abs(position_t - held_position_t)`, with first-entry turnover measured
from the declared flat initial position. A long-to-short flip has turnover 2.
The first row is explicitly marked `initial_boundary`: period return is NaN/false,
held position is the declared initial 0, and gross P&L is the known starting 0.
This is an accounting boundary, not a market-return observation. Step 096 can charge
the initial entry there; future metrics must distinguish it from realized intervals.
There is no automatic terminal liquidation or fabricated future exit.

## Hand-calculated five-bar check

These are synthetic test values, not market observations. Scale and lag are 1:

| Row | Close | Alpha/position | Held position | Period return | Gross return | Turnover |
|---|---|---|---|---|---|---|
| 0 (boundary) | 100 | 1 | 0 | unavailable | 0 | 1 |
| 1 | 110 | -1 | 1 | 0.10 | 0.10 | 2 |
| 2 | 99 | 0.5 | -1 | -0.10 | 0.10 | 1.5 |
| 3 | 99 | 0 | 0.5 | 0 | 0 | 0.5 |
| 4 | 108.9 | 1 | 0 | 0.10 | 0 | 1 |

## Availability, alignment and lineage

Bars retain their source index/order. Alpha is aligned by exact int64 UTC-microsecond
timestamps, independently of its row labels. Timestamps must be unique, chronological
and on the declared interval grid; alpha timestamps outside the supplied bars are
refused. No nearest matching, sorting, filling or invented rows occurs. An optional
bar symbol column must match the alpha symbol. Finite close prices must be positive;
unknown/non-finite prices make both adjacent returns unavailable.

Missing alpha values/rows remain unavailable as signals. Startup/warm-up positions
are explicitly flat until the first usable execution (not fabricated alpha values).
After trading starts, a missing current signal does not erase
the return of a known previous position, but unknown positions are never forward-filled.
Gaps invalidate returns and execution lags spanning missing intervals, and turnover
once exposure is active. Known flat startup carries no invented trades across gaps.
History before the initial boundary is not synthesized. Each table value family has
an explicit availability mask; invalid arithmetic stays NaN/false. Inputs and outputs
do not share mutable data.

The returned `GrossSimulation` carries the verified experiment ID, frozen position
config and hash, starting code commit/dirty state, optional experiment snapshot ID,
symbol and table. It is an in-memory computation, not a persisted AlphaResult.
No measured profitability, validation/test scores or promotion are claimed.
Synthetic tests cover timing, exact alignment, scales, delays, gaps, invalid
inputs, future perturbation/truncation and real open/closed experiment checks.

## Fees and net returns (step 096)

`helios.sim.costs.simulate_net` accepts the same registered experiment and position
inputs. `apply_costs` can also consume an existing `GrossSimulation` in memory.
The default configuration is `configs/fees.yaml`, unchanged from ADR-005:
`cost = turnover * (taker_fee_bps + slippage_bps[symbol]) / 10000`.
There is no half-turnover factor or extra round-trip multiplier. A position flip
from +1 to -1 has turnover 2. Maker fees are not used in this taker model.

The returned `NetSimulation` preserves gross lineage, a canonical fee JSON snapshot,
its SHA-256 hash, effective per-side basis points, and an isolated table containing
`cost`, `cost_available`, `net_return`, and `net_available` alongside gross columns.
Unknown costs or gross returns make net returns unavailable, without zero filling.
Initial entry costs are charged on the explicit accounting boundary. No synthetic
terminal liquidation is charged. For the five-bar example above, BTC costs are
`[0.0012, 0.0024, 0.0018, 0.0006, 0.0012]`, and net returns are
`[-0.0012, 0.0976, 0.0982, -0.0006, -0.0012]`.

## Return, volatility and Sharpe (step 100)

`helios.sim.metrics.simulation_metrics(net)` calculates an immutable in-memory
summary of a complete `NetSimulation`. Its horizon comes from the recorded
position interval: `1h` uses H-HOURLY (8,760 periods/year), `1m` uses H-MINUTE
(525,600). Values come from `configs/splits.yaml` and the complete config hash is
recorded. Unsupported or unconfigured horizons fail explicitly.

The pure `return_metrics(returns, periods_per_year=...)` kernel accepts only finite,
real, one-dimensional observed-period net P&L. Fractions retain the simulator's
reference exposure convention: **total return is the sum**, without reinvesting
or compounding. Following ADR-002/003:

- Mean return = total / observed periods; annual return = mean × periods/year.
- Per-period volatility = sample standard deviation (`ddof=1`); annual volatility
  = per-period volatility × sqrt(periods/year).
- Per-period Sharpe = mean / per-period volatility, with risk-free rate zero;
  annual Sharpe = per-period Sharpe × sqrt(periods/year).

Zero variance gives a defined zero volatility and undefined (`None`) Sharpe, even
for constant positive returns. With one observed period, sample volatility and
Sharpe are undefined. Non-finite values and arithmetic overflow are refused.
Tiny returns are scaled before variance calculation to avoid false zero variance
from squaring underflow. No epsilon changes the denominator.

The first table row is an accounting boundary, not an observed interval. For
moments, its net entry expense is added to the first actual interval's net P&L;
this is recorded as `entry_cost_in_first_interval_v1`. Thus the five-row example
has **four observations**, `[0.0964, 0.0982, -0.0006, -0.0012]`, and total net
return **0.1928**. No fee is discarded, and no extra starting-zero observation or
terminal exit is fabricated. A table containing only the initial boundary has
its actual total entry expense, zero observed periods and undefined period/annual
metrics. This convention concerns the simulator's reference exposure accounting;
it is not compounded portfolio NAV or executable fill accounting.

The wrapper requires chronological, unique timestamps and every interval present
on the UTC grid, a single first-row boundary, boolean availability masks and
finite available net values. Missing periods or unknown net P&L fail; they are
never dropped, zero-filled or forward-filled. Known flat startup periods remain
actual observations. Split selection and warm-up validity remain later work.

`SimulationMetrics` records the metric config JSON/hash, splits hash, symbol,
experiment/snapshot, position and fee hashes, source commit and dirty flag. Its
numeric summary is isolated from later table mutations. The wrapper creates no
persisted result, gate decision or TEST authorization. Family Sharpe values
must not be compared across horizons: daily aggregation and other metrics belong
to step 101.

For the synthetic observed series `[0.01, -0.02, 0.03, 0.01]` and four periods/year,
total and annual return are both 0.03, sample variance is 0.000425, period
volatility is sqrt(0.000425), and annual Sharpe is `0.015 / sqrt(0.000425)`.
These hand calculations and the entry-fee example are covered by unit tests;
they imply no actual market performance.

Daily Sharpe, turnover, drawdown and directional hit rate are implemented in step
101; see [simulator diagnostics](SIMULATOR_DIAGNOSTICS.md) for their conventions.
