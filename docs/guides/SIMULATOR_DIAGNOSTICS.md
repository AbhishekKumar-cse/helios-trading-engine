# Simulator diagnostics

These functions calculate immutable in-memory diagnostics from simulated inputs.
They do not persist AlphaResults, authorize TEST access, execute trades or claim
market performance. Example numbers in tests are synthetic.

## Daily Sharpe, turnover, drawdown and hit rate (101)

`simulation_diagnostics(net)` retains the step-100 `SimulationMetrics` lineage
and records a canonical diagnostic configuration and hash. It requires complete,
contiguous net simulation data, as step 100 does. Turnover is total actual
`abs(position change)` (including initial entry), divided by the number of actual
observed intervals. A lone boundary has total turnover but no mean turnover.

`daily_metrics(times, net_returns, interval="1h")` also works independently on
known observed intervals: net P&L is summed by each row's `open_time` UTC date,
and daily Sharpe uses sample standard deviation and sqrt(365). At least 30
observed days are required (ADR-003). Completely absent days are omitted, never
filled with zeros. Days with fewer than 24 hourly / 1,440 minute observations are
retained and flagged `has_gaps`, including partial edge days. Unknown/non-finite
P&L cannot be submitted as observed data. Zero variance gives undefined Sharpe.
The simulation wrapper folds the initial entry expense into the first actual
interval before daily aggregation, consistently with step 100.

Drawdown is the maximum peak-to-trough decline of **additive cumulative net P&L**
from the declared zero reference starting point, not a compounded NAV percentage.
Initial entry loss is included. Duration is the longest peak-to-recovery episode
or peak-to-end for unrecovered drawdowns, in actual periods and microseconds.
Magnitude and longest duration need not concern the same episode. The boundary
itself adds no elapsed period; a lone initial loss has zero elapsed duration.

Hit rate follows spec section 19: the fraction of observed intervals where
`sign(held_position) == sign(period_return)`. Ending-bar positions are not used.
Zero/zero counts as a directional match under this literal convention; it is not
a winning trade. If any market return or held position is unknown, hit rate is
undefined and `n_hit_periods` records the known interval count. High hit rate
does not establish positive net profitability.

Pure kernels and the wrapper are covered by hand-calculated drawdown episodes,
the existing five-bar entry/flip/exit example, hourly/minute daily equivalence,
missing-day/gap cases, insufficient samples and invalid-input tests.

## Fitness (102)

`fitness_result(diagnostics)` uses the family's **annual net Sharpe**, arithmetic
annual net return and mean turnover. ADR-002 fixes
`Fitness = Sharpe * sqrt(abs(annual_return) / max(turnover, floor))`.
The default floor remains 0.125 from `configs/gates_v1.yaml`; the sign comes from
Sharpe. Zero turnover uses the floor. Missing prerequisite metrics yield N/A,
while negative turnover, non-finite settings and arithmetic overflow fail.

The result retains the complete simulation diagnostics, denominator, versioned
formula/floor JSON and hash, and the exact gate configuration JSON/hash. Passing
an explicit alternative configuration records its different hashes; it does not
change or approve the accepted default. This is a calculation, not a promotion
or gate verdict. Four tests reproduce ADR-002's A/B/C/D examples exactly; further
tests cover zero/missing values, sign, overflow and configured lineage.

## Predictive IC and IC-IR (103)

`information_coefficients(alphas, bars, config=ICConfig(...))` accepts a declared
coin-to-`AlphaSeries` mapping and matching per-coin bars. It aligns signals by
exact UTC timestamps, independently of row labels. The forward outcome is
`close[t+h] / close[t] - 1`; it is an evaluation label, never a trading feature.
The positive integer horizon counts actual intervals. Missing intervals spanning
a label, unknown endpoint prices/signals and the final h endpoints are unavailable.
Each coin records total/paired/unavailable counts; nothing is filled or fabricated.

Both Spearman (default, average ranks for ties) and Pearson are supported.
Constant inputs and fewer than two pairs give N/A. Overall time-series IC is
reported per coin. Monthly IC uses UTC calendar months and purges labels ending
in another month. Time-series IC-IR is mean of defined monthly ICs divided by
their sample standard deviation, without annualization. Undefined months remain
in the report; fewer than two defined months or zero variance gives N/A.

Cross-sectional IC uses only same-timestamp, available signal/outcome pairs,
requiring at least **five** instruments at that timestamp (QNT-008). Smaller
universes, constant cross-sections and timestamps with insufficient pairs remain
N/A with explicit point-level symbols and a report-level reason. `cross_mean` is
the mean of defined timestamp ICs. Cross-sectional IC-IR uses the series of UTC
monthly mean ICs, with crossing label windows purged, rather than pretending every
timestamp is an independent subperiod.

The result stores immutable tuples, config JSON/hash, hashes of the exact input
timestamps/prices/signals/masks, and an optional caller-supplied snapshot ID.
The snapshot ID is not invented or independently verified by this pure kernel.
The later registered-result pipeline attaches experiment/code lineage and must
provide only authorized split data; this helper does not load or grant TEST access.
Tests cover perfect/inverse signals, tied ranks, constants, five-coin availability,
gaps, monthly purging/IR, timestamp alignment and future-price perturbation.

## Cost sensitivity (104)

`cost_sensitivity(gross)` returns five immutable points for cost multipliers
0.5, 1, 2, 3 and 4. It snapshots the same gross execution table and split settings
once, then scales the fee/slippage basis points and recalculates net P&L and
step-100 metrics. The taker cost model remains unchanged: no extra round-trip
factor, new execution, terminal liquidation or position remapping occurs.

The original fee JSON/hash is retained; every point records its multiplier,
effective one-side basis points, total cost, scaled fee JSON/hash and complete
simulation metric lineage. The accepted default fee file is not modified.
`cost_stress_sharpe` returns the annual family Sharpe at 2x cost, as ADR-002/005
require. Undefined Sharpe remains N/A. A custom curve must have at least five
positive, finite, unique ascending multipliers; absence of a 2x point yields N/A
for that property. The curve is returned, not written as an authorized result.

The synthetic five-bar example has gross total 0.2 and base total cost 0.0072:
the five net totals are 0.1964, 0.1928, 0.1856, 0.1784 and 0.1712. Tests also
cover zero turnover, immutable input/config snapshots and invalid/unknown data.
Sharpe itself is not asserted to decline monotonically: cost changes can affect
both the mean and variance.
