# Lagged positions and gross returns (step 095)

`helios.sim.positions.simulate_gross` accepts one coin's bounded alpha, its bars,
an explicit interval and an execution lag of at least one decision interval.
It verifies a real open preregistered experiment through the caller's PostgreSQL
connection before computation. No result, experiment, promotion or trade is created
by the simulator. Costs/net returns, metrics, splits and gates remain later steps.

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
No measured profitability, costs, metrics, validation/test scores or promotion are
claimed. Synthetic tests cover timing, exact alignment, scales, delays, gaps, invalid
inputs, future perturbation/truncation and real open/closed experiment checks.
