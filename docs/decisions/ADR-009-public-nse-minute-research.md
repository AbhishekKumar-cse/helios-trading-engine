# ADR 009 Public NSE minute research and operational evidence

Status: Accepted implementation scope, 2026-10-18, following the user's request
to complete the equity extension and use public sources without a provider account.
Experimental research assumptions remain explicit. This extends ADR 007 and
ADR 008; it does not change the crypto protocols or relax promotion criteria.

Use the public Upstox V3 historical candle endpoint with ISIN-based NSE instrument
keys. Retain every response, request range, exclusion and SHA-256. Freeze the
current official Nifty 50 roster; do not present it as historical index membership.
The first collection covers 2025-01-01 through 2026-06-30 for all 50 companies.
It contains actual minute observations only. Do not fill missing minutes, infer
trade direction, manufacture bid/ask quotes or download reserved TEST prices.
Public endpoint access was observed without credentials; continued access and
timely delivery are not guaranteed.

Use normal weekday NSE sessions, 09:15–15:30 Asia/Kolkata. Retain the official
2026 capital-market holiday response, verify its hash, and reject dates outside
its year coverage. Special sessions are excluded explicitly. Evaluate complete
375-slot sessions conditionally, with missing and zero-execution-volume sessions
reported. This ex-post cohort is not a causal outage-management strategy.

Minute features reset at session boundaries and minute gaps. The ten causal
features describe returns, short volatility, candle shape, relative volume,
bar opening gap and session slot. Their windows mean minutes, not hourly windows.
The target is the next adjacent minute's open-to-close direction. A feature's
availability never depends on the future label. TRAIN ends 2025-12-31; VALID is
2026-01-09 through 2026-06-30. TEST remains sealed by the equity evaluator.

Pool all 50 companies for a fixed LightGBM fit through 2025-09-30. Calibrate
expected returns on 2025-10-09 through 2025-12-31. Sample every fifth UTC minute
for fit and calibration only, fixed before fitting to control memory. Keep 100
trees, 15 leaves, minimum child 200, learning rate .03 and seed 42; no VALID
early stopping or parameter search. Evaluate every available VALID minute.
Calibrated expected payoff must exceed both sides' frozen cost scenario to enter.

Preregister the first minute execution benchmark on RELIANCE, rather than claim
all-company minute strategy evaluation. Test three quantitative baselines
(momentum, reversal, volume shock), eight additional fixed formulas and one ML
definition. The hourly extension tests the same eight additional formulas on
all 50 companies, plus a separate volume-shock reference baseline. All attempted
definitions, stocks, failures and INVALID outcomes remain in the registry.

Run the shared strategy, risk, OMS, simulated venue and INR ledger. Trade whole
shares long-only. Execute a decision at the next observed opening; the final
calendar-known flat target exits at the observed 15:29 minute opening. Use the
existing INR 100,000 per-session capital, 50% allocation, 15 bps commission/tax
proxy plus 5 bps slippage per side and a separate 2x-cost execution. These are
research assumptions, not a broker tariff or observed spread. Aggregate returns
by session with 252 sessions/year. Minute turnover divides daily traded
notional/capital by 375 scheduled full bars. No cross-frequency ranking is valid
without common dates and explicit source/window differences.

Up to four isolated execution workers may replay independent sessions. Workers
receive data only, have no database handles, and return results in chronological
order. A sequential/process parity check must compare accounting and fills.
Preregistration records the worker count. Frozen source copies allow the ongoing
development tree to change without changing an in-flight experiment. Archived
dirty=true lineage is never relabelled clean after a later commit.

G7 continues to block promotion: historical membership, corporate actions,
special sessions, executable liquidity and dated costs remain unverified.
Record a no-eligible selection review; never force a winner or consume TEST
because the semester is ending. Existing global TEST counters and crypto
definition/result fingerprints must remain unchanged.

Public live observation is a separate OBSERVE service. It stores actual raw
responses, heartbeat gaps, elapsed time and terminal failures, including access
denials. It has no order path. Its uptime is not PAPER trading. The NSE PAPER
adapter uses the shared components and actual later Yahoo last-trade timestamps;
late candles, stale quotes, gaps or risk trips halt it. A bounded entry point
requires clean source, registered minute formula/instrument and an open normal
session. It is integration-only, with no restart/reconciliation or promoted-trial
claim. Steps 166, 167 and 170 still require their actual elapsed operational
evidence. Supervisor approval of an alternative exit criterion is not assumed.

Sources checked 2026-10-17: [historical candles](https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/),
[intraday candles](https://upstox.com/developer/api-documentation/v3/get-intra-day-candle-data/),
[rate limits](https://upstox.com/developer/api-documentation/rate-limiting/),
[NSE holiday source](https://www.nseindia.com/api/holiday-master?type=trading).
