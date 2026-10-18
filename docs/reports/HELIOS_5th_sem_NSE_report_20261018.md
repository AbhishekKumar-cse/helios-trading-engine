# HELIOS Equity Research

Fifth semester implementation and measured research review

## 1 Introduction

We extended HELIOS from crypto bar research to public NSE equity data and reused its evaluator, backtester, risk, OMS, simulated venue, INR ledger and registry. The result is a working research framework and retained experiments. This report does not claim a profitable alpha or completion of the required seven-day PAPER trial.

### Purpose and scope

The academic goal is to turn an alpha hypothesis into an auditable measurement: frozen data, causal features, a declared split and costs, simulated execution, gates and immutable evidence. The new equity scope uses the current Nifty 50 companies. It does not claim reconstructed historical index membership, BSE-specific ingestion or live real-capital trading.

### Motivation and tools

Prediction accuracy alone does not establish an executable trading edge. HELIOS therefore keeps feature availability, costs, fill timing and candidate rejection visible. We use Python 3.12, NumPy, pandas, PyArrow, Pydantic, LightGBM, SQLAlchemy/PostgreSQL, pytest/Hypothesis and a local Streamlit lab. Dependencies are locked. Bulk market data and credentials remain outside version control.

## 2 Literature review

The implemented workflow separates data, signals, orders and accounting. Ke and colleagues [6] describe LightGBM as a gradient-boosted tree implementation. We use it as a fixed classifier backend; the paper's benchmark results are not NSE trading results. Isotonic regression maps TRAIN-tail predictions to expected returns.

Bailey and colleagues [7] explain how searching many strategies on finite historical data creates backtest overfitting and false discoveries. We retain trial counts, rejected attempts and sealed TEST boundaries for transparency. We have not estimated their probability of backtest overfitting or implemented their combinatorially symmetric cross-validation procedure. Preregistration alone does not establish freedom from selection bias.

The data sources have different purposes. Nifty Indices provides the current constituent roster; Yahoo distributes daily/hourly NSE-listed prices; public Upstox V3 supplies historical minute candles. The NSE capital-market holiday response supplies normal-session calendar evidence for 2026. OHLCV data cannot reconstruct bid/ask spreads, queue position or order-book flow. These limits constrain the conclusions more than the choice of classifier.

The contribution is an evidence-preserving integration and a measured negative research programme. We do not claim a new profitable trading method, state-of-the-art predictive performance or an independently replicated microstructure study.

## 3 Research requirements

### 3 1 Functional requirements

Collect actual observations with source timestamps, request ranges and hashes. Reject malformed or inconsistent bars and retain exclusions. Do not manufacture missing prices or backdate fills. Keep TRAIN, VALID and sealed TEST separate. Preregister candidate definitions before their new VALID P&L is measured.

Evaluate formula and ML alphas through the same strategy, independent risk, OMS, simulated execution, costs, ledger and versioned gates. Retain rejected and INVALID outcomes. Display source coverage, simulated fills, costs, daily equity and report links in the lab. Execution is simulated only.

### 3 2 Nonfunctional requirements

Every result must identify code, dirty state, data snapshot, policy, model/calibration hashes and random seed. Archived development source remains dirty even after later commits. Causality, ledger and order conservation checks protect shared behavior. A reproducibility claim requires an actual replay, not only a file checksum.

Infrastructure failures must remain visible. A computed artifact whose database write failed may be registered from that exact retained computation; it must not be presented as a fresh simulation. Unobserved runtime is left NULL. Unstarted preregistered experiments may resume from unchanged source and model. Recovery scheduling and hashes are recorded separately.

### 3 3 Assumptions and constraints

The universe is today's frozen 50-company roster, with survivorship risk. Corporate actions, historical membership, special sessions, executable liquidity and a dated broker cost schedule are not fully verified. G7 therefore blocks promotion. Complete-session backtests are conditional ex-post studies, not a feasible outage-selection rule.

Equity research assumes INR 100,000 independent capital per stock/session, long-only whole shares and at most 50% allocation. Costs are a 15 bps commission/tax proxy plus 5 bps slippage per side, with a separate 2x-cost replay. These figures are declared scenarios rather than broker invoices, observed spreads or guaranteed bounds.

## 4 System design

### 4 1 Research workflow

Source bytes → validated bars → causal features → preregistered formula or fixed ML alpha → strategy → risk → OMS → simulated venue → INR ledger → daily metrics and gates → registry and reports.

The existing continuous UTC crypto clock and USDT defaults remain intact. NSE sessions explicitly use Asia/Kolkata, 09:15 to 15:30. Hourly execution includes six full hours and the observed final 15-minute bar. Minute execution uses 375 normal slots. Each replay begins and ends flat. Decisions fill at the next observed opening; calendar-known exits use the actual final opening, never an invented closing trade.

### 4 2 Data and feature modules

The completed public minute snapshot contains 6,865,386 bars for all 50 companies from 2025-01-01 through 2026-06-30, with zero failed monthly requests. Nine hundred monthly responses, the official roster, exclusions, Parquets, collector source and request journal are retained and hashed locally. Reserved equity TEST dates were not downloaded for this minute round.

Ten minute features describe short returns, volatility, candle body/range/location, relative volume, opening gap and session slot. Their windows reset at session boundaries and missing minutes. The supervised target is the next adjacent minute's open-to-close return. Feature availability does not depend on the future target. Missing or zero-volume execution sessions remain explicitly excluded.

### 4 3 Model and experimental design

The minute classifier pools all 50 companies. Its fixed TRAIN sampling rule keeps every fifth UTC opening minute for fit and calibration only. It fits through 2025-09-30, excludes the intervening embargo and calibrates expected return from 2025-10-09 through 2025-12-31. VALID is 2026-01-09 through 2026-06-30; VALID never fits or selects this model. Actual fit and calibration counts are 686,644 and 207,497 samples.

The fixed LightGBM specification uses 100 trees, 15 leaves, minimum child size 200, learning rate 0.03 and seed 42. Expected payoff must clear both sides' proxy costs before entry. The previous prediction pilot, whose stopping used VALID, remains separately labelled and is not substituted for this TRAIN-only alpha.

The hourly extension tests eight additional fixed hypotheses across all 50 companies, plus the volume-shock reference. Alongside the original momentum, reversal and ML definitions this makes 12 hypothesis types. The first minute execution benchmark is RELIANCE: three quantitative baselines, eight additional formulas and one ML definition. All-company TRAIN fitting is not an all-50-company minute strategy result.

Independent execution workers receive data only and return chronological session evidence. Frozen source archives isolate ongoing experiments from development edits. Infrastructure recovery may schedule independent experiments concurrently without changing their per-experiment execution policy or numerical parameters.

### 4 4 Storage and operational boundaries

PostgreSQL stores preregistration, definitions, result lineage, gates, orders, fills and audit events. Raw data, models, inputs, source archives and execution JSON/HTML remain on disk with fingerprints. The local lab reads retained evidence; it does not refit a model when a user changes the company selector.

The NSE PAPER adapter reuses the shared strategy/risk/OMS/venue/ledger and supports INR whole shares. A genuine later Yahoo last-trade timestamp is required for a public-price fill proxy. Stale candles, quotes preceding an intent and feed gaps halt risk and cancel pending orders. A bounded runner requires clean source, registered NSE metadata and an open normal session. These are integration controls, not evidence that a market-hours NSE PAPER trial occurred.

## 5 Measured results

Four retained rounds contain 612 measurements: the original hourly round has 100 REJECTED quantitative results and 50 INVALID ML results; the 50-company volume-shock reference and 400 added hourly measurements are all REJECTED. The completed RELIANCE minute round has 11 REJECTED quantitative results and one INVALID ML result. These are repeated company measurements across 12 hypothesis types, not 612 independent ideas. No candidate is eligible or promoted, and global TEST access remains zero.

The minute verifier reconciled 242,381 base fills across 1,243 candidate/session replays. Each of the 11 quantitative definitions used 113 observed normal sessions. These sessions cover the expected normal-session grid for this frozen calendar; the earlier source, historical-membership, corporate-action and execution limitations still apply. The ML output is flat after the TRAIN-calibrated cost hurdle and is INVALID, with unavailable performance metrics rather than a fabricated zero-return strategy.

Minute turnover overwhelms the measured gross contribution under the declared costs. Across the 11 quantitative candidates, the mean daily net result ranges from -18.88% to -9.08% of the independent INR 100,000 session capital. Every candidate's aggregate net result is negative. Gross attribution uses the exact base executed quantities valued at observed opens; fees and slippage reconcile exactly to retained net P&L. It is not an independently rerun zero-cost strategy. Both base and doubled-cost results are actual shared-engine replays.

For example, body reversal has 29,536 base fills over 113 sessions. Gross attribution is INR 3,732.10, fees are INR 934,453.550450925 and modeled slippage is INR 311,484.51775. Net P&L across these independent resets is INR -1,242,205.968200925. A sum larger than 100% is possible because capital resets per session; it is not a compounded multi-day account or a sustainable live allocation. The large losses expose excessive churn in these fixed formulas under the stated cost model.

The hourly and minute RELIANCE diagnostics share 111 observed dates, 2026-01-09 through 2026-06-30. Daily-aggregated Sharpe is negative for all 11 quantitative pairs; ML remains N/A. Vendors, feature windows and complete-session cohorts differ, so this comparison cannot establish causal frequency superiority or a tradable ranking. The detailed tables, gross/base/2x cost plot and hashed result references are in docs/research/nse_equity_closeout_20261018.json and its companion review.

The final review records SKIPPED_NO_ELIGIBLE_CANDIDATES without changing registry selection rows. G7 stays false for every attempt. Original crypto fingerprints remain 25 definitions and 34 results, with no overwritten evidence. Database and WSL lineage-preflight interruptions remain in the recovery audit. Exact computed artifacts were recovered without replay and unknown runtime remains NULL.

### Reproducibility and verification

With seed 169, we selected a stored MAXHEALTH hourly momentum result and imported its hash-verified archived source. Replaying base and 2x costs reproduced 111 sessions, 116 base fills and 777 ledger snapshots exactly, excluding generated execution identities. No model was refitted, no new result was registered and TEST remained untouched.

Final Ruff lint and formatting pass for 315 Python files, and strict mypy passes for 131 source files. With PostgreSQL restored, the full regression run passed 1,801 tests and had one type-check subprocess timeout under host load; one slow test was deliberately deselected. The unchanged type-contract test subsequently passed within its original 90-second limit on a byte-identical Linux filesystem copy. This is a focused resolution, not a claim that a single full-suite invocation was entirely green. Two added instrument/persistence tests also passed against PostgreSQL inside a rollback.

A later performance-only simulator change reuses compiled Pydantic numeric validators with unchanged constraints. Its 38 focused ledger, venue, property, hand-calculation, event-loop and PAPER regressions passed. Replaying one retained RELIANCE minute session at base and doubled costs produced identical financial fill fields, returns and every ledger snapshot against the archived source. That one session took 15.43 seconds with archived code and 8.15 seconds with current code under the observed host load; this is not a general throughput guarantee. Frozen research continues to identify and use its original source. Current code also corrects a legacy minute Bar source tag; hashed inputs and result provenance always identify the actual Upstox source.

Separate 90-second host and container OBSERVE smokes completed without continuity gaps during market closure, with zero candles, quotes or fills. These verify bounded operation only. Current public RELIANCE metadata was retained and registered with lot size 1 and tick INR 0.1. Synthetic acceptance tests and actual rolled-back PostgreSQL persistence do not substitute for observed market-hours PAPER execution.

The live local lab was checked for public minute coverage, completed results, TRAIN and calibration counts, simulated fills and reference equity. Branch-protection review confirms the required main CI and leakage contexts. New work remains uncommitted on main; remote CI for these edits requires a later authorized commit and push.

## 6 Limitations and remaining work

No candidate is promoted from the current source-validation cohort. Negative research is useful evidence, but it does not satisfy the original promoted-alpha seven-day trial. A verified no-eligible review must keep TEST sealed; neither more ML nor a deadline justifies lowering gates or inventing a best strategy.

Public Upstox history worked without credentials at collection time. This is not a guarantee of continued access or live-feed timeliness. The public NSE quote endpoint returned HTTP 403 and was not bypassed. The separate OBSERVE service records raw responses and heartbeat gaps without orders. Its bounded smoke and any later uptime are not PAPER fills or a promoted-candidate trial.

Steps 166, 167 and 170 still require actual always-on PAPER operation, an eligible promoted candidate, seven days of observations and the same-date backtest comparison. A full market-hours NSE PAPER and kill-switch recording is also pending for step 174. Team onboarding and other-laptop evidence for 010 and 022 remain administrative gaps. Optional step 168 is preparation for later order-book work.

The SRS addendum and carryover file record source/corporate-action/calendar/cost validation, causal feed handling, instrument provenance, live acceptance and restart reconciliation. These requirements are not silently waived. A supervisor-approved alternative academic exit criterion would need an explicit recorded decision.

## 7 References

[1] HELIOS architecture decisions and implementation scope ADR 001 through ADR 009, repository docs/decisions, reviewed October 2026. Each file retains its own recorded approval status.

[2] Nifty Indices, Nifty 50 constituent list, https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv, frozen October 2026.

[3] Upstox, Historical Candle Data V3 and Intraday Candle Data V3 API documentation, https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/ and https://upstox.com/developer/api-documentation/v3/get-intra-day-candle-data/, checked 17 October 2026.

[4] NSE, Trading holiday calendar, https://www.nseindia.com/api/holiday-master?type=trading, retained official capital-market response for 2026.

[5] HELIOS measured evidence, docs/research/nse_shared_research_20261017.json and nse_archived_reproduction_20261017.json, plus the new per-round verification records and retained local execution artifacts. Bulk datasets are intentionally not embedded in this report.

[6] G. Ke et al., LightGBM A Highly Efficient Gradient Boosting Decision Tree, Advances in Neural Information Processing Systems 30, 2017. https://papers.nips.cc/paper/2017/hash/6449f44a102fde848669bdd9eb6b76fa-Abstract.html

[7] D. H. Bailey, J. M. Borwein, M. Lopez de Prado and Q. J. Zhu, The Probability of Backtest Overfitting, revised working paper, 27 February 2015. https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf
