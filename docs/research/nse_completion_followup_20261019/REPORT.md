# Certification assessment and paper-strategy integration

The three paper-inspired prototypes now have measured end-to-end shared-engine
results. **Source certification and eligible-alpha acceptance remain unmet.**

## Data certification

The new assessment verified all **57 retained minute-file hashes** and **492
reference response bodies**, bound to the existing snapshot and archived audit
source. Its verdict is **NOT_CERTIFIED**: 16 companies remain blocked and 41
remain conditional screen inputs. No exclusion, adjustment, source eligibility
or promotion gate was changed.

Official daily identities, corporate-action records, daily extreme-price
diagnostics and reference charge evidence are retained per company in
[certification_assessment.json](certification_assessment.json). They do not
establish exact original minute/share/volume units. Missing evidence remains:

- Independent raw-minute vintage and the effective identity/adjustment chain.
- Publication/receipt history and a causal outage/eligibility policy.
- Dated account tariff/contract-note acceptance.
- Executable spread/depth, latency and participation/fill calibration.

The [provider documentation](https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/)
describes candle fields. The [exchange historical-data page](https://www.nseindia.com/static/market-data/eod-historical-data-subscription)
describes its order/trade data products. The assessment retains fresh public
documentation receipts and any refusals; neither a documentation page nor a daily
aggregate supplies the missing observations. The [public brokerage schedule](https://zerodha.com/charges/)
remains a scenario rather than proof of a historical account's accepted billing.
No paid subscription, login workaround or guessed price/share repair was used.

## Shared-engine integration

Frozen round **nse_papers_shared1** preregistered all three unchanged candidates
on RELIANCE before new scoring. It uses the full January 9–June 30, 2026 frozen
conditional VALID window, 114 sessions per candidate, INR100,000 independent
daily capital, fixed whole shares, long-only next-opening execution and unchanged
normal/doubled costs. Relative-volume ranking inputs cover the 41 screened
historical companies; this does not claim execution on all 41 companies.

| Candidate | Sharpe | Fitness | Net INR | Doubled-cost net INR | Gates |
|---|---:|---:|---:|---:|---:|
| Closing momentum | -6.2927 | -6.4706 | -5,979.09 | -11,454.26 | 2/8 |
| ORB / relative volume | -2.5440 | -1.3560 | -1,606.64 | -2,720.21 | 2/8 |
| Noise / VWAP | -1.4743 | -0.8211 | -1,754.12 | -4,289.68 | 2/8 |

All three are **REJECTED**. The new opt-in holding mode targets only at binary
state changes, preserving actual filled shares instead of issuing a new target
on each held minute. It permits one entry per session; risk blocks are not
silently retried. Legacy behavior and configuration hashes retain their defaults.
The shared evaluator rejects signal-hash drift or an execution mode that differs
from preregistration. Missing history is excluded explicitly, never scored as a
zero-return session. The unchanged turnover gate still uses per-bar units and
rejects these sparse strategies. G7 also remains false. No threshold was relaxed.

The independent audits reconciled **180 base fills over 342 candidate-sessions**,
including 90 active and 252 observed flat sessions, flat-end INR accounting,
statutory settlements, normal/stressed returns and all eight gate decisions.
The schedule audit verified fixed quantities, decision-before-opening timing,
41 ranking source files and 321 strictly previous history windows. **630 earlier
TRAIN decision records match the original frozen paper screen exactly.**

See [shared checks](shared_checks.json), [schedule checks](schedule_checks.json),
[summary](summary.json) and the actual quantitative definitions in `definitions/`.
The raw source, model-lineage files and large execution artifacts remain local
under `reports_out/equity_research/nse_papers_shared1`.

## Interpretation and closure

Full default regression: **1,863 passed**, one existing slow test deselected,
15 existing warnings. New integration tests cover next-opening timing, exact
whole-share fees, future-price perturbations, history holes, binary/single-entry
guards, registry persistence and preregistered execution/input-hash mismatch.
Strict typing and Ruff lint/format checks pass.

All pre-existing definitions, results and experiments are unchanged. The registry
now has 64 definitions, 667 results and 667 experiments; the increase is exactly
three quantitative definitions/results/experiments. Global TEST access remains
zero and no candidate was promoted.

These strategies were already screened on reused TRAIN and earlier VALID
outcomes were known. This is exploratory integration measurement, not fresh
independent confirmation. Existing TRAIN-only model/calibration files supply
required evaluator lineage only; no model was refitted or used for predictions.
Actual execution used frozen development source based on commit `eb5c58d` with
**dirty=true**, preserved in every result. A later commit must not relabel it.

Technical integration is complete for this bounded scope. The certification
goal needs the missing independent evidence above. Eligible-alpha acceptance
needs a strategy that actually passes the accepted gates, followed by independent
confirmation and governed selection. A specified number of profitable winners
cannot be manufactured by reversing metrics, choosing favorable subsets or
repeating exposed VALID until a winner appears.

The scheduled market-hours PAPER test was not edited or rescheduled. It still
requires clean, authorized source and its operational prerequisites at wakeup.
These new implementation changes are uncommitted under the repository workflow.
Reproduction and validation commands: [guide](../../guides/NSE_PAPER_STRATEGY_RESEARCH.md).
