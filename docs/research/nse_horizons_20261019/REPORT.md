# NSE longer-horizon TRAIN follow-up, October 19, 2026

The shared paper-strategy integration and certification audit were committed and
pushed as `f7398746b2c841168c6de8d938aec5a897d85af9`. Its GitHub
[CI passed](https://github.com/AbhishekKumar-cse/helios-trading-engine/actions/runs/39294856797).
This follow-up adds three fixed longer-horizon ML diagnostics and an independent
audit. **There is still no eligible alpha and no positive data certificate.**

## Fixed TRAIN research

The protocol was saved before preparation, and execution restarted from a frozen
source archive. Source was based on `f739874` with **dirty=true**; the later commit
does not change that measurement lineage. All selected source files were hashed.
Only 2025 TRAIN candles were decoded: VALID and TEST prices were not loaded.
The 41-company cohort remains conditional and selected retrospectively, with
incomplete or quarantined sessions excluded explicitly. This is exploratory work
on previously used TRAIN data, not fresh independent confirmation.

First-30-minute relative price/range/volume features predict a return from the
following opening, using three fixed exits: 60 minutes, 120 minutes and the final
session opening. The model uses 100 LightGBM trees, 15 leaves, minimum child size
200, learning rate 0.03 and seed 42. There is no parameter grid. Fit uses January
through August (6,023 company-days); isotonic expected-return calibration uses
September only (811). October 1-8 is embargoed; the screen uses October 9 through
December 31 (2,055 company-days). No screen labels fit either model or calibration.

Entry requires calibrated expected gross return above the fixed **21 bps** hurdle.
An independent INR 100,000 daily account targets INR 50,000 in whole shares sized
at the known decision close, holds those shares and exits intraday. Normal costs
use the existing dated fee estimator plus 5 bps adverse slippage per side; stress
doubles charges and slippage. Account averages are diagnostics, not an executable
multi-stock portfolio or benchmark-relative alpha. These are TRAIN screens, not
new shared-evaluator registry results.

| Fixed target | Maximum calibrated expected return | Active trades | Screen survivors |
| --- | ---: | ---: | ---: |
| 60 minutes | 1.1734 bps | 0 | 0 |
| 120 minutes | -1.7163 bps | 0 | 0 |
| Session close | -2.4041 bps | 0 | 0 |

All three remain below the hurdle and stay in observed cash. All company/target
outcomes are retained in [results.json](results.json), including zero survivors
across 123 company/target combinations. Flat returns have undefined Sharpe,
represented as null. They are not profitable results. No hurdle, gate or
calibration was changed after observing this screen.

The separate verifier checked all frozen source hashes, chronological masks,
sample labels/timestamps, one direct source session for each company, all saved
model predictions, independently refitted September calibration, every entry
decision, all 12,330 session/scenario records and every zero-return summary.
It deliberately refuses a round with active trades, which would require a fill
audit. [verification.json](verification.json) records the successful audit.

## Certification remains unmet

The prior [certification audit](../nse_completion_followup_20261019/REPORT.md)
rehashes 57 minute files and 492 daily-reference response bodies. It records
16 blocked and 41 conditional companies, with zero releases. The missing evidence
includes independent raw share/volume vintages and corporate-action chains,
historical publication/receipt/outage timing, and accepted account costs plus
executable spread/depth/latency/fill calibration. Existing quarantines stay intact.

One additional unauthenticated request was made to Upstox's documented ISIN
corporate-action endpoint. It returned **RemoteDisconnected, no HTTP status and
zero response bytes**, not an HTTP authentication denial. The retained
[receipt](probe_receipt.json) records one attempt, no authentication,
no TEST prices and no source release. The documentation's request example uses
a Bearer token ([official endpoint documentation](https://upstox.com/developer/api-documentation/get-corporate-actions/)).
An event list alone would not establish the unit vintage of retained candles.
NSE also documents a historical order/trade subscription
([official data page](https://www.nseindia.com/static/market-data/eod-historical-data-subscription));
no subscription was purchased and no credentials were requested or supplied.

## Reproduction and limits

Use the documented WSL Python environment, from the repository root:

```bash
python scripts/research_nse_horizons.py \
  --snapshot data/equities/nifty50_repaired/20261018_v2 \
  --output NEW_exclusive_directory
python scripts/verify_nse_horizons.py --root NEW_exclusive_directory
```

Do not rerun the existing `reports_out/equity_research/nse_horizon_train1`
directory. That exclusive local archive contains protocol, exact source, models,
calibration, sample table, exclusions and all records. The compact evidence
manifest binds the copied results and audit to that archive.

Four focused tests pass, covering future-data perturbation, exact opening labels,
gap/session rejection, known-price sizing, fixed shares under cost stress and
explicit unavailable data versus observed cash. The preceding integration's full
regression passed 1,863 tests; those counts are separate. No accepted ADR, gate,
registry row, selection, TEST access, promotion or scheduled PAPER test changed.

The completed work is the technical integration, frozen model experiments and
verification. Certification requires the missing independent evidence; eligible
alpha requires measured performance through the unchanged gates and independent
confirmation. Neither acceptance outcome can be completed by declaring an
uncertain source certified or a rejected/flat model profitable.
