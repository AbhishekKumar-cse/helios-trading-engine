# Nifty 50 shared-engine research — 2026-10-17

The equity pipeline now reaches the shared evaluator, reference backtester,
strategy/risk/OMS/simulated venue/INR ledger, metrics, gates, result registry and
HTML reports. Round `nse_hourly_round1` completed all 150 preregistered VALID
attempts over the frozen 50-company universe. Each attempt is retained.

| Candidate | Companies | Result |
|---|---:|---|
| Long-only hourly momentum | 50 | 50 REJECTED |
| Long-only hourly reversal | 50 | 50 REJECTED |
| TRAIN-only calibrated LightGBM | 50 | 50 INVALID: CONSTANT_ALPHA |

Neither formula had a positive total net return in this conditional cohort.
The ML calibration's maximum expected next-hour return was about 15.37 bps,
below the frozen 40-bps round-trip cost hurdle. Its trading signal therefore
stayed flat; no fictitious trades or ranked performance metrics were created.
No candidate was promoted. This completes the integration, not the discovery of
a profitable alpha.

The classifier used 20,185 fit samples through 2025-09-30 and 3,319 separate
TRAIN-tail calibration samples from 2025-10-09 through 2025-12-31. Hyperparameters
were fixed; VALID did not fit, calibrate or early-stop the model. VALID covered
2026-01-09 through 2026-06-30. The previous prediction pilot remains separate.

Independent verification reconciled all **11,743 base fills** and **11,006
independent stock/session replays** against observed source openings, whole-share
long-only quantities, configured slippage/fees and final flat INR balances.
All artifact/source/model/calibration/input hashes, preregistration timestamps,
registry round trips, base/stress return metrics, Fitness and gates passed.
Fill IDs are unique across the combined execution evidence. Complete observed
session coverage ranged from 94.74% to 97.37%.

The existing crypto registry stayed unchanged: 25 definitions and 34 results,
with identical before/after fingerprints. Global TEST accesses remained **0**.
New equity records comprise three definitions, 150 results, a registered prefix
snapshot and 151 finished experiments (one fit plus 150 evaluations).

Validation: full regression suite **1,784 passed**, one slow test deselected;
final equity/UI focused suite **13 passed**, including the new session fill-ID
check. A subsequent dashboard wording check passed all four dashboard tests.
Ruff lint/format and mypy (122 source files) passed. Live dashboard and report
verification are recorded in the local project context.
After the clean-CI typing correction, uncached mypy again passed all 122 source
files, all nine equity integration tests passed, and immutable artifact/registry
reconciliation passed without fitting models or rerunning research attempts.

The frozen source was archived from main commit
`d2078d3a4124feada2b4b6a13fd794bf2ed40b53` with `dirty=true`. Committing this
implementation later does not change that historical run lineage. Post-round
production edits update the lab's introductory wording and correct explicit
collection/status types in the evaluator after clean CI identified typing errors.
The status construction remains equivalent; execution calculations are unchanged.
Archived/current hashes are explicitly listed in the verification JSON. The
actual round's frozen execution source and saved results remain unmodified.

Evidence: [verification JSON](nse_shared_research_20261017.json), local immutable
artifacts in `reports_out/equity_research/nse_hourly_round1/`, and read-only
reconciliation script `reports_out/verify_nse_round.py`. Snapshot ID:
`efa4a6dc7b0c115a476421a4daf6916aca145691bc09e8c524c367a0ac2c3303`.

Open [the Nifty lab](http://localhost:8501/?page=equities), choose a company,
then inspect **Alpha research · shared engine**. Reports use the common retained
run links; the main alpha registry marks these definitions `nse_cash`.

These results use ex-post complete-session selection, current constituents,
vendor calendar/price data and explicit proxy costs of 15 bps commission/tax
plus 5 bps slippage per side. They are conditional development simulations with
unverified historical membership, adjustments and corporate actions. G7 blocks
promotion. Missing sessions remain unknown; no bars or liquidation fills were
invented. Hourly integration is complete; minute strategy research still needs
substantially more history. No live trading or 24-hour PAPER trial was run.

Protocol: [ADR-008](../decisions/ADR-008-nse-shared-research-loop.md) and
[execution guide](../guides/NSE_SHARED_RESEARCH.md).
