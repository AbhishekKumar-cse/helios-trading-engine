# NSE hourly research through the shared engine

Run from the repository root in the documented WSL environment:

```bash
/home/abhi/.venvs/helios/bin/python -m helios.equities.pipeline \
  data/equities/nifty50/20261017T112815Z_2528ceac --round-id nse_hourly_round1
```

The round name is immutable. A completed or partially started directory cannot
be overwritten. A new research question needs a new round name and preregistration;
do not silently rerun candidates to replace their previous outcomes.

Open [the Nifty lab](http://localhost:8501/?page=equities), select a company and
inspect **Alpha research · shared engine**. It shows retained candidate results,
observed-session coverage, simulated INR fills/fees and a reference equity curve.
Report links open the same hash-verified HTML reporting path as crypto. The main
alpha registry also includes the equity definitions, marked `nse_cash`.

## Connected components

`sim.evaluate.evaluate(..., equity=context)` dispatches explicitly to the NSE
adapter. The old crypto configuration, bar store, fees, splits and clock retain
their previous defaults. NSE tickers retain their actual names, including `&`
and hyphens; observed timestamps are never shifted onto Binance's UTC grid.

The adapter uses the common formula DSL, reference backtest engine, bar strategy,
risk checks, OMS, paper execution venue, average-cost ledger, return metrics,
Fitness function, G1–G6 comparison kernel, result registry and HTML renderer.
NSE-specific session/configuration and coverage rules surround these shared
components. It does not substitute classification accuracy for strategy P&L.

Three frozen hypotheses run over all 50 companies: long-only one-hour momentum,
reversal, and ML expected-return signals. The new classifier fits only through
2025-09-30; a separate 2025-10-09..12-31 TRAIN tail calibrates expected next-hour
returns using isotonic regression. The fit uses fixed hyperparameters with no
VALID early stopping. VALID is 2026-01-09..06-30. The previous prediction pilot
is retained separately, because its stopping was selected with VALID.

All 150 VALID experiments are preregistered before the first VALID P&L evaluation.
Models, calibration, source files, source prices, policies and gates have hashes.
The registry retains unsuccessful and INVALID attempts. Constant signals and
insufficient observations have no rankable metrics. Passing comparisons does not
automatically promote a candidate. TEST access is refused before loading data.

## Execution and interpretation

Each normal observed weekday session has six full hours from 09:15 plus the
observed fifteen-minute closing bar at 15:15. Decisions execute at the next
observed opening through the shared engine. An explicit calendar-known flat target
exits at that final-bar opening; every replay must finish flat. Shares are whole,
long-only, and quoted in INR. Entry and exit both pay costs. No synthetic bar,
terminal fill, overnight return or missing-session return is manufactured.

The cost scenario assumes 15 bps per side for commission/taxes plus 5 bps slippage.
This is a research proxy, not an observed spread, broker invoice or guaranteed
upper bound. Stress replays both components at 2x through the same engine.
Fills assume unlimited liquidity at a bar-opening price proxy. Capital is fixed
INR 100,000 per independent stock/session; results are arithmetic reference P&L,
not compounded portfolio returns. Annualisation assumes 252 trading sessions.
Turnover is traded notional/capital divided by six scheduled full hours/session.
Execution accounting retains 18 decimal places; registry metric columns retain
their existing 10-decimal precision. Full numerical evidence remains in artifacts.

**Results are conditional on complete sessions selected ex-post.** Incomplete
sessions, zero-volume execution bars and inconsistent bars are excluded explicitly,
with reasons and coverage. Missing sessions stay unknown, not flat/zero. This is
a data-quality development study, not a feasible live outage-selection strategy.
The vendor daily calendar is not an independently verified exchange calendar.

G7 blocks promotion while historical membership, source adjustments, corporate
actions and calendar quality remain unverified. G8 records a minimum 90% observed
complete-session coverage. A profitable-looking conditional result therefore
cannot become a promoted equity alpha from this round.

The round stores immutable artifacts under `reports_out/equity_research/ROUND/`:
source archives, fixed protocol, TRAIN/VALID-only input snapshot, ML/calibration,
preregistered experiments, per-run execution/gate artifacts and registry outcomes.
The same snapshot is registered in PostgreSQL. Before/after fingerprints verify
that existing crypto definitions/results and global TEST access did not change.
Development runs record `dirty=true` with archived source; no clean reported-run
claim is made. Bulk data/models/fill logs remain outside Git.

Hourly is the first complete equity integration. Daily remains the prediction
pilot/calendar source; minute strategy research requires substantially more
history. This does not start an NSE live feed or paper-trading service.

Decision record: [ADR-008](../decisions/ADR-008-nse-shared-research-loop.md).

First completed round: [measured outcomes and verification](../research/nse_shared_research_20261017.md).
