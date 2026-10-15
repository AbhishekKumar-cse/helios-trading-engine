# Minute round one: hourly versus minute (165)

The frozen minute round produced **no eligible candidate**: all eleven quantitative
VALID measurements are REJECTED, and minute ML is INVALID. Step 163 verified an
empty final TEST shortlist and recorded twelve REJECTED deployment decisions.
Step 164 recorded a verified skipped candidate backtest. Global TEST access is
still **zero**. No candidate is promoted.

## Comparison on a daily basis

| Evidence | Retained attempts | Daily-aggregated annual Sharpe | Performance conclusion |
|---|---:|---|---|
| Hourly baselines, quantitative and ML | 22 (19 VALID, 3 TRAIN) | N/A: all INVALID | No valid performance ranking |
| Minute quantitative VALID | 11 | Table below; all negative | Every candidate fails accepted gates |
| Minute ML VALID | 1 | N/A: INVALID | No performance conclusion |

Daily Sharpe uses **UTC daily sums of net arithmetic reference P&L**, divided by
their sample standard deviation (ddof=1), multiplied by sqrt(365), with zero
risk-free return. It is derived from saved daily diagnostics, **not** by scaling
minute Sharpe or comparing annualised per-bar Sharpe across frequencies. The
verifier independently rebuilt each UTC-day sum from the retained per-period
series, reconciled entry expense and total net return, then checked the saved
daily Sharpe against an independent sample-variance calculation.

| Minute alpha | Daily-aggregated annual Sharpe | UTC days | Observed periods | VALID measurement |
|---|---:|---:|---:|---|
| minute_b0 | -102.0624 | 180 | 259,031 | REJECTED |
| minute_b1 | -250.1675 | 180 | 259,031 | REJECTED |
| minute_b2 | -346.7309 | 180 | 259,031 | REJECTED |
| minute_h01 | -209.1058 | 180 | 259,031 | REJECTED |
| minute_h02 | -121.0528 | 180 | 259,031 | REJECTED |
| minute_h03 | -111.9621 | 180 | 259,031 | REJECTED |
| minute_h04 | -478.1265 | 180 | 259,031 | REJECTED |
| minute_h05 | -146.4367 | 180 | 259,031 | REJECTED |
| minute_h06 | -162.0871 | 180 | 259,031 | REJECTED |
| minute_h07 | -143.5286 | 180 | 259,031 | REJECTED |
| minute_h08 | -220.7413 | 180 | 259,031 | REJECTED |

All eleven use BTCUSDT, the frozen minute snapshot and unchanged accepted costs.
There are 180 observed UTC days per candidate, from 2025-09-02 through 2026-02-28.
The first day has 1,271 realised periods after the declared 168-row warm-up and
initial accounting boundary; the remaining 179 days each have 1,440 periods.
The saved `has_gaps` flag marks that first partial day; it is warm-up/boundary
coverage, not an invented exchange outage. The initial entry expense is assigned
to the first realised interval. No missing bar or unavailable signal is filled.

These are additive reference returns, not compounded self-financing NAV. Severe
negative Sharpe and additive losses below -100% do not describe a solvent account
continuing to trade after bankruptcy. An execution backtest remains unavailable.

The hourly VALID window is 2023-01-08 through 2024-06-30; minute VALID is
2025-09-02 through 2026-02-28 (ADR-004). They do not overlap. Daily aggregation
normalises the sampling convention, but cannot repair INVALID hourly evidence or
make different market windows a matched experiment. **No hourly-versus-minute
winner, relative profitability or horizon advantage can be established.** Hourly
unavailability remains N/A, never zero or a loss inferred from missing data.

## What failed and what was retained

Every quantitative minute candidate fails G1, G2, G5 and G6. Some also fail G3;
G4 passes because these are VALID measurements. The [cost reality report](minute_cost_reality.md)
shows gross edge per turnover around -0.07 to +0.07 bps versus accepted 12 bps
per side; every candidate remains net-negative even at half costs. These fixed
stress cases do not change fees or execution policy and do not authorize tuning.

The [minute ML report](minute_ml_results.json) retains all 259,199 VALID alpha
outputs as typed UNAVAILABLE, with zero diagnostic periods. Its maximum gross
edge estimate is 4.01249 bps versus 24 bps round-trip costs; classifier accuracy
does not substitute for usable net trading evidence. No retrospective
calibration, backfill or diagnostic substitute was promoted into a result.

Hourly attempts retain their original gap/unavailability failures. Their
[round-one note](hourly_round1.md) and [backtest skip](hourly_bar_backtest.md)
remain valid. The public PAPER integration using rejected minute_h04 and the
synthetic hand accounting fixture are operational/correctness evidence only.
Neither supplies an independent candidate performance result or matched comparison.

## Reproducibility

The [comparison evidence](minute_round1_comparison.json) records all 34 retained
attempts with their original commit/configuration/snapshot/seed and artifact
SHA-256, plus the saved daily diagnostic hash, coverage and independently checked
Sharpe for each usable minute attempt. The read-only derivation used clean source
`d53bda36c8b0a61eaedefee784d0f69a1509dc4e`; the standalone verifier's SHA-256 is recorded separately.
It read hash-verified saved evaluation artifacts in a repeatable-read, read-only
transaction. It loaded no market observations, reevaluated no alpha, fitted no
model and accessed no TEST split. Bulk series remain ignored outside Git.

The eleven quantitative results were measured on clean source 68d66a1 and the ML
result on clean source 2f45359. Their original measurements and provenance stay
unchanged. Exposure to hourly outcomes and fixed preregistered minute hypotheses
was disclosed before minute research; this comparison is descriptive research,
not a fresh untouched holdout. Accepted fees, splits, availability, lineage and
G1-G6 are preserved. Future work requires a new preregistered research round;
these results do not justify moving to a faster horizon or deploying an alpha.
