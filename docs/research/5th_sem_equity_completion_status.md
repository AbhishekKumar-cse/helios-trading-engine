# Fifth semester completion after the NSE extension

Review updated 2026-10-18. The public-data implementation, expanded hourly
research, minute execution round and sampled archived replay are complete.
The original operational exit criteria remain unmet;
this assessment does not waive them or claim a profitable alpha.

The latest [minute-breadth and PAPER safety follow-up](nse_followup_closeout_20261018.md)
adds AXISBANK, SUNPHARMA and TCS execution: six REJECTED quantitative outcomes
and three INVALID ML outcomes. No candidate passes the gates. The new
[certification assessment](nse_execution_certification_20261018.md) covers 57
companies, 369 official reference sessions and 18,468 stock-days; it remains
NOT CERTIFIED. Raw unit, volume, causal-availability and executable-liquidity
proof are still missing. Official daily identity facts do not remove those gaps.
Local full regression now passes 1,850 tests, with one existing slow test
deselected and 15 existing warnings; Ruff/format and strict types pass.
The new safety work is uncommitted on main and has no new remote CI claim.
Independent verification reconciles 132,206 base fills and 684 candidate/session
replays, including dated reference charges and settlements. All 138 archived
research source files match commit 6ce3a0b byte-for-byte. The protocol/summary
Git markers are false, while all 9 immutable evaluator markers are true after
working-tree edits began; those markers are preserved independently, never
relabelled clean. See the [source check](nse_breadth_source_lineage_20261018.json)
and [round verification](nse_minute_breadth_checks_20261018.json).

The follow-up [source and trading assumption audit](nse_assumption_validation_summary_20261018.md)
is complete. It checked all 900 raw monthly files and all 50 stock Parquets,
collected public NSE corporate actions and compared 44 official daily files.
It found 321,060 minutes before documented index inclusions, 135 sampled price
scale flags across seven stocks, 37,500 excluded Budget-session candles and a
3,000-minute short-session cohort in TRAIN. These findings require a new dataset
and protocol before a validated historical-Nifty research claim. The previous
results remain conditional current-company studies and are not overwritten.

The follow-up rebuild now exists separately: **6,909,518 actual minute bars across
57 historical companies**, with **5,069,595 screened bars from 41 companies**.
It removes 323,310 out-of-membership minutes, records temporary demerged membership,
and implements 368 full sessions plus one 60-minute session. ADR010 adds causal
per-fill charge accrual and explicit day-end STT settlements through the shared
simulator/INR ledger. The new model fit uses 505,528 TRAIN and 152,405 separate
calibration samples. New conditional VALID round `nse_minute_repaired1` completed:
two REJECTED quantitative results and one INVALID constant ML alpha. Independent
checks reconciled 43,665 base fills across 228 candidate/session replays, including
tax settlements, ledger cash, metrics and gates. All 612 earlier artifact hashes
and crypto fingerprints remain unchanged; TEST access is zero. See the
[verified closeout](nse_rebuild_closeout_20261018.md) for this separate round.
Known capital-action units remain quarantined; exact minute/volume certification,
causal outages and observed execution assumptions still block G7. See the
[rebuild guide](../guides/NSE_REBUILD.md) and
[data checks](nse_rebuild_data_checks_20261018.json). Full regressions: 1,830 passed,
one existing slow test deselected, 15 existing warnings; strict types and Ruff pass.

## Implemented and measured

- Public Upstox minute history for all 50 current Nifty companies: **6,865,386
  retained bars**, 2025-01-01 through 2026-06-30, with zero failed monthly
  requests. Raw responses, roster, exclusions and hashes remain local/ignored.
- NSE minute features, chronological availability/labels, TRAIN-only LightGBM
  fit and disjoint TRAIN-tail calibration. Actual samples: **686,644 fit** and
  **207,497 calibration**, pooling all 50 companies. VALID never fits this model.
- Shared hourly/minute evaluator, strategy, independent risk, OMS, simulated
  venue, whole-share INR ledger, metrics, costs, stress, gates and registry.
- **600 completed hourly company attempts**: original three definitions across
  50 stocks, eight additional hypotheses across 50, and a separate 50-stock
  volume-shock reference. All 400 additional outcomes were REJECTED; their
  44,173 base fills and 44,024 stock/sessions independently reconciled. The
  reference and original rounds have their own retained verification evidence.
- The first minute execution benchmark is **RELIANCE**, with twelve preregistered
  definitions: **11 REJECTED and one INVALID ML**. Independent verification
  reconciled 242,381 base fills over 1,243 candidate/session replays. All eleven
  quantitative results lose after costs. The final cost attribution and hourly
  comparison use 111 common observed dates; this is a conditional diagnostic.
  In that original round, the other 49 companies contribute to TRAIN only.
  The separate reconstructed-data baseline round now executes AXISBANK,
  SUNPHARMA and TCS through the shared engine; all nine outcomes fail eligibility.
  This is four distinct companies with minute execution evidence including RELIANCE,
  not an all-company execution result.
- Actual archived-source replay for **169**: seed 169 selected MAXHEALTH momentum;
  111 sessions, 116 base fills and 777 ledger snapshots matched exactly. No refit,
  new measurement or TEST access. Generated execution IDs alone were excluded.
- Read-only branch-protection API review and explicitly labelled screenshot for
  **171**; controlled SRS addendum/ADR 009 for **172**; explicit carryover for **175**.
- Template-derived measured report for **173**, with all eight rendered pages
  inspected and preserve-only package parts checked against the original template.
- Public-data NSE PAPER adapter and bounded runner; synthetic tests verify
  genuine later timestamp requirements, stale-intent cancellation, whole-share
  INR accounting and actual PostgreSQL persistence inside a rolled-back fixture.
  Current RELIANCE metadata was registered from a retained public Kite dump:
  lot size 1, tick size INR 0.1. It does not establish historical tick rules.
- Equity-aware atomic dashboard kill, fresh-close startup, silent-feed halt and
  cancellation, exclusive PostgreSQL process ownership with connection-loss
  detection, and crash recovery that checks durable fills against every stored
  ledger/position checkpoint. Synthetic tests cover pending intents, non-flat
  inventory, corrupt accounting, ownership conflict and audit rollback.
  Recovery halts the old scope and never invents an exit fill or resumes trading.
  See [NSE PAPER recovery](../guides/NSE_PAPER_RECOVERY.md). Actual open-session
  feed/kill/process-stop acceptance remains outstanding; Sunday preflight
  collected zero observations/fills and recorded uncommitted source.
- Separate OBSERVE host/container smokes each measured 90 seconds, without gaps,
  candles or fills during market closure. They do not establish PAPER trading.

The implemented stock source is NSE-listed equities. A separate BSE price
collector has not been implemented; the company ticker BSE in the Nifty roster
is not evidence of BSE-exchange ingestion.

## Requirements still open

| Step or scope | Remaining evidence |
|---|---|
| 166 | Always-on **PAPER** deployment and an actual unattended 24-hour trial. The new Compose service is OBSERVE only. The bounded PAPER runner still needs clean source and real market-hours feed acceptance. |
| 167 | An eligible promoted candidate and seven actual days of PAPER records. G7 still blocks this public/current-universe cohort. Do not force a winner or call a rejected-candidate integration trial promoted trading. |
| 170 | PAPER versus backtest over the same seven observed days, after that trial occurs. Historical simulation or two 90-second smokes cannot substitute. |
| 174 | Authentic complete demonstration including market-hours NSE PAPER and kill switch. A historical research walkthrough alone does not meet this condition. |
| 010, 022 | Teammate onboarding, clones and other-laptop evidence. This workstation cannot establish those facts. |
| 168 optional | Tick/order-book source and recorder, scoped separately for the sixth semester. |

Source validation remains substantial: point-in-time index membership, corporate
operations/ticker continuity, special sessions, causal feed-outage/liquidation
handling, effective-date brokerage/taxes/rounding and observed liquidity/slippage.
The audit now supplies actual membership-change notices, 124 returned corporate
events and an explicit dated exchange/IPFT and side/order/day charge diagnostic.
It does not certify a complete historical membership history, raw share units,
dated broker contract or executable liquidity. The charge estimator is separate
from the frozen execution policy and has not been substituted into old results.
The existing 15+5 bps-per-side cost scenario is unchanged and explicitly a proxy.
Complete-session research is selected ex-post. G7 prevents a tradable or promoted
claim even if a numerical gate passed. Equity TEST stays sealed.

Current RELIANCE tick/lot metadata and unit tests do not solve public quote
latency or restart reconciliation. The public NSE quote endpoint returned 403
and was not bypassed. Continued free-source access is not guaranteed. Expanding
minute execution beyond the first benchmark needs new explicit preregistration.

## Evidence and workflow

[Final measured review](nse_equity_closeout_20261018.md),
[minute verification](nse_minute_round1_verification_20261018.json),
[academic report](../reports/HELIOS_5th_sem_NSE_report_20261018.docx),
[hourly expansion verification](nse_hourly_round2_verification_20261018.json),
[reference verification](nse_hourly_reference_verification_20261018.json),
[archived replay](nse_archived_reproduction_20261017.json),
[observer smokes](nse_public_observer_smoke_20261018.json),
[current metadata](nse_public_instrument_20261018.json),
[public-minute guide](../guides/NSE_PUBLIC_MINUTES.md), and
[carryover](../../6thSem/carryover_from_5th.md).

Infrastructure interruptions are retained, including database-write artifacts
recovered without replay and lineage-preflight retries from unchanged source.
No existing result or crypto evidence was overwritten. Unknown recovered runtime
is NULL. Reports retain dirty development lineage and exact source archives.

Strict types pass for 131 source files. Full regression with PostgreSQL restored
passed 1,801 tests with one type-check subprocess resource timeout (one slow
test deselected). The unchanged type-contract test then passed within its
original limit on a byte-identical Linux copy; this does not claim a single
entirely green full-suite invocation. Two new metadata/persistence checks passed.
Compiled-validator reuse subsequently passed 38 focused simulator/PAPER tests
and exact archived/current minute accounting parity at base and doubled costs.
Final Ruff lint/format passed 315 files. This assessment records local
verification before publication; new-commit remote CI is checked separately.
Existing branch checks are strict; administrator enforcement remains false.

No qualifying equity alpha, 24-hour PAPER soak or seven-day trial is claimed.
A supervisor-approved alternative academic exit criterion would need an explicit
recorded decision; no such approval is assumed here.
