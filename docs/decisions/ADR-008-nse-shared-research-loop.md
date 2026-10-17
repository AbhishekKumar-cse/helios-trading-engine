# ADR-008: Connect NSE hourly research to the shared engine

Status: Accepted scope (explicit user instruction, 2026-10-17); experimental
execution, cost and coverage assumptions below. Does not supersede crypto ADRs.

Connect the equity adapter to `sim.evaluate.evaluate`, the existing formula DSL,
reference `backtest.engine.simulate`, strategy/risk/OMS/paper venue/ledger, common
metrics/Fitness/gate comparison kernels, HTML reporting and immutable registry.
Begin with hourly intraday research over the frozen 50-company universe. Daily
prices provide source-calendar evidence; the short minute sample is not used for
strategy claims. No TEST access, live orders or automatic promotion.

Preserve the continuous UTC crypto clock and USDT accounting defaults. NSE bars
explicitly name `nse_regular_v1`, INR instruments require an allowlist, and whole
shares use a separate strategy configuration. Legacy crypto serialization must
retain its previous shape. Never rename NSE tickers into fabricated USDT pairs
or shift observed timestamps onto the Binance UTC grid.

For normal observed weekday sessions use 09:15–15:30 Asia/Kolkata: six full hours
plus the observed final fifteen-minute bar. Each shared-engine replay is one
flat-to-flat session. Decisions execute at the next observed opening. A fixed
calendar-known flat target at 15:15 executes at the real final-bar opening.
Missing final bars, nonstandard clocks and zero-volume execution bars exclude
that session explicitly; no invented liquidation or zero-filled returns.

**Coverage is an ex-post conditional complete-session study.** It is not a claim
to a feasible outage-selection strategy. Missing/incomplete sessions remain
unknown and coverage is reported. The daily vendor calendar is not an independent
official holiday/special-session or historical-membership source. Source quality,
survivorship, adjustments and corporate actions remain promotion blockers (G7).
G8 records minimum complete-session coverage of 90%.

Costs are an explicit research scenario: 15 bps commission/tax proxy plus 5 bps
slippage per side, with 2x stress rerun through the same execution engine. They
are not a verified NSE/broker invoice, observed spread or guaranteed upper bound.
Capital is INR 100,000 per independent stock/session, maximum allocation 50%,
whole shares, long-only, simulated unlimited-liquidity market fills. Arithmetic
daily P&L is measured on fixed capital; 252 sessions/year is an assumption.
Turnover is actual traded notional/capital divided by six scheduled full hours.

Use frozen equity TRAIN/VALID dates from ADR-007. Preregister momentum, reversal
and ML candidates before any new VALID P&L. The new ML model fits through
2025-09-30, excludes 2025-10-01..08, and calibrates expected next-hour return with
isotonic regression on 2025-10-09..12-31. Fixed 100 trees, 15 leaves, minimum child
200, learning rate .03, seed 42; no early stopping or parameter search. Models and
calibration are available only after TRAIN ends. VALID labels never fit or select
this model. Do not reuse the previous pilot model, whose stopping was selected
with VALID. Net expected payoff must cover both sides' proxy costs before entry.

Equity gates use their own `nse_hourly_gates_v1` identity and reuse common G1–G6
comparisons with the recorded equity metrics. G7 blocks promotion unconditionally
for this vendor/current-universe development cohort. INVALID attempts retain
reasons without ranked metrics. All experiments and results carry source/data/
policy/model/calibration fingerprints; development runs retain dirty=true and
their archived source even after later commits. Existing crypto research remains immutable.

Sources checked 2026-10-17:
[NSE market timings](https://www.nseindia.com/static/market-data/market-timings),
[broker charge categories](https://zerodha.com/charges/). The proxy above is a
chosen modelling assumption, not a transcription of the linked fee schedule.
