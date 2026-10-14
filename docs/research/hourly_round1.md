# Hourly round one: no candidate promoted

Selection review: 2026-10-15. **All eight candidates are REJECTED for deployment**
because their VALID measurements are INVALID. The original immutable result rows
remain INVALID, with Sharpe/Fitness null. This is a data-validity outcome, not
evidence of negative profitability. No valid best candidate can be named.

Eight fixed BTCUSDT hourly hypotheses were preregistered in experiments 4482–4489
before YAML registration or evaluation. Each has one version and one parameter
setting, one-hour horizon, seed 0 and 168 explicit warm-up rows. Evaluations used
the accepted splits, fees and G1–G6 without changing them after inspection.
Source `e34bc248a8ca43884471d3cefb9582299c452509` was clean for all eight attempts;
snapshot `9d75c8de86a8e981a9af61b17f76d1a7efc225f3d554366a152ba8f03968824f`.

| Candidate | Experiment | VALID measurement | Unavailable after warm-up | Selection |
|---|---:|---|---:|---|
| hourly_h01 | 4482 | INVALID | 4 | REJECTED |
| hourly_h02 | 4483 | INVALID | 24 | REJECTED |
| hourly_h03 | 4484 | INVALID | 24 | REJECTED |
| hourly_h04 | 4485 | INVALID | 1 | REJECTED |
| hourly_h05 | 4486 | INVALID | 47 | REJECTED |
| hourly_h06 | 4487 | INVALID | 168 | REJECTED |
| hourly_h07 | 4488 | INVALID | 167 | REJECTED |
| hourly_h08 | 4489 | INVALID | 168 | REJECTED |

Every row records DATA_GAPS and UNAVAILABLE_AFTER_WARMUP. Registered artifacts,
definition identity and original source/snapshot lineage were verified. No
missing prices or unavailable signals were filled, dropped or converted to flat
positions to manufacture a usable P&L series. The baseline comparison is also
unavailable: B0–B2 have nine retained attempts (three preliminary VALID checks,
then three TRAIN and three VALID comparisons), all INVALID. There are **17 total
simulation attempts across 11 fixed definitions**. All attempts and earlier
checks remain visible; repeated checks are not mislabeled as extra parameter
variants. Details and hashes: [search effort](hourly_search_effort.md) and
[original hypotheses](hourly_hypotheses_round1.md).

The final TEST shortlist uses the latest clean VALID evidence, complete accepted
G1–G6 and VALID Fitness ranking, with at most two selections. All candidates fail
eligibility. The executed decision is **SKIPPED_NO_ELIGIBLE_CANDIDATES** with empty
outcomes; every candidate and baseline TEST-access count remains **0**. There is
no TEST result, TEST Sharpe, independent confirmation or profitable strategy to
report. The accepted maximum of two accesses per version is preserved. The plan
artifact is `reports_out/hourly_final_test/c9cd4c63-134f-4c95-b9e0-65f79a5886d5/plan.json`.

Deployment selection decisions are stored as append-only
`ALPHA_SELECTION_DECISION` records in the existing `audit_events` journal and read
by `helios.registry.selection.get_selection`. Each records its round, version,
original VALID run/artifact hash, reason, actor, accepted gate hash and clean
decision source. Repeating the same decision returns it; conflicting evidence
requires a new round. No measurement or definition is updated to make it look
REJECTED/PROMOTED. Promotion requires matching, reserved TEST evidence and all
accepted gates on both VALID and TEST. This journal currently fingerprints each
decision; it does not claim the later global audit-chain implementation.

The separate hourly ML work has modest predictive development scores: logistic
accuracy 0.537994, LightGBM 0.542763 vs majority 0.502807; ridge is slightly worse
than its constant-return comparator. One VALID isotonic fit on the frozen
LightGBM predictions changes same-row Brier from 0.247652 to 0.247409. That is
resubstitution, and VALID also selected LightGBM's stopping iteration. It is not
independent calibration performance or alpha profitability. Calibration experiment
4994 saved a verified reliability SVG; its artifacts completed before an
experiment-finalization API error was repaired without a second fit.

ML transformation experiment 4995 freezes TRAIN conditional return means and
explicit entry/exit costs, then trailing 168-hour normalization and clipping.
It saved 63,945 typed AlphaValues; all historical VALID values are UNAVAILABLE
because they predate the fitted calibration map. Its 13,655 retrospectively
normalized diagnostics are separate. Registering this ML alpha and passing it
through the same simulator/gates remains step 145; no ML alpha was promoted here.

The next research round needs an explicitly documented treatment of incomplete
market history and signal availability before performance conclusions. Any changed
definition/policy must receive new lineage and preregistration; the current v1
attempts cannot be silently repaired and rerun. There is no rationale for touching
TEST merely because this development round failed. Paper venue, fill-booked
ledger and complete backtest integration are subsequent work, not demonstrated
by these research diagnostics.
