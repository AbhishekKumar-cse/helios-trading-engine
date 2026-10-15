# Hourly candidate bar backtest: verified skip (151)

Decision on 2026-10-15: **SKIPPED_NO_ELIGIBLE_CANDIDATES**. No candidate
backtest was executed. The user explicitly chose this disposition over preparing
an unranked diagnostic. Step 150's reporting implementation and synthetic
correctness demonstration were already completed, committed and pushed.

A fresh read-only registry review verified all **22 retained research attempts**
across **12 non-synthetic hourly definitions**, including the frozen ML alpha.
Every measurement remains **INVALID**, with Fitness and Sharpe NULL. All eight
quantitative selection decisions remain REJECTED; no alpha is promoted and no
rankable best candidate exists. Neither predictive accuracy nor the number of
unavailable rows supplies a replacement profitability ranking.

| Group | Definitions | Retained attempts | INVALID | TEST accesses |
|---|---:|---:|---:|---:|
| Baselines B0–B2 | 3 | 9 | 9 | 0 |
| Fixed quantitative candidates h01–h08 | 8 | 8 | 8 | 0 |
| Frozen ML alpha | 1 | 5 | 5 | 0 |
| Total | 12 | 22 | 22 | 0 |

The review checks every registered evaluation artifact's SHA-256, alpha/version,
split, snapshot and source lineage, together with all eight selection-decision
hashes. It compares the complete original result and definition rows with the
saved pre-step-146 fingerprints; both remain unchanged. No market data was
loaded, TEST observations accessed, model refitted or candidate reevaluated.
No experiment, backtest run, order, fill or P&L snapshot was created. The sole
existing backtest remains `hand_20261015`, a synthetic accounting fixture whose
19.340022 USDT net P&L is not candidate or market performance.

The committed [review evidence](hourly_bar_backtest_review.json) retains every
attempt's run/experiment IDs, original commit/config/snapshot/seed, validity
reasons and artifact checksum. The verification ran against clean source
`e9f65c31ec9e85941f5ad81da8b3b473d349b6fb` in a repeatable-read, read-only
database transaction. Its local verifier's SHA-256 is recorded separately from
that source commit; the verifier is not claimed to be part of that commit.

Review SHA-256:
`62137b47152226de616d196b1a407c8dca648fad361dcc14ef1c2378799a0020`.
The local standalone HTML is
`reports_out/backtests/hourly_step151/report.html`; it displays the skipped
status and unavailable performance explicitly. P&L, drawdown, exposure and trade
statistics for a candidate execution remain **N/A**, not zero.

This closes the requested review with the agreed skipped outcome; it does not
establish an executed candidate backtest or gate approval. Executing one later
requires separately preregistered usable candidate evidence and an explicit
data-quality policy. The accepted chronological splits, gap handling, signal
availability, costs, gates and original INVALID results remain unchanged.

Related evidence: [round-one selection](hourly_round1.md),
[frozen ML evaluation](hourly_ml_alpha_evaluation.md),
[execution report definitions](../guides/BACKTEST_REPORT.md).
