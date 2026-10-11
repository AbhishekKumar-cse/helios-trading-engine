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
