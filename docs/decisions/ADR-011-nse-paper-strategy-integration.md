# ADR 011: NSE paper-strategy execution integration

Status: Proposed design record, 2026-10-19. Experimental implementation and
measurement are within the user's instruction to complete certification
assessment and paper-strategy integration. Extends ADR010 without changing its
source exclusions, fees or promotion rules. Design acceptance remains a separate
team-lead decision; no gate change or source-release approval is assumed.

The three literature-inspired candidates remain the fixed, previously screened
closing-momentum, relative-volume opening-range breakout and noise-band/VWAP
adaptations. Their failed TRAIN screens are retained. Full shared-engine replay
is an integration measurement on previously exposed VALID, not new independent
confirmation or permission to optimize parameters until a winner appears.

Use a separate `nse_paper_minute_features_v1` feature namespace and an explicit
`paper_state_change_v1` execution option. Preregistration binds that option and
each signal-input hash. Binary long/flat state changes issue targets through the
existing strategy/risk/OMS/venue/ledger. Repeated held states issue no additional
notional target, preserving actual filled whole shares. Decisions execute at
the next observed opening. Calendar-known exit remains at the final observed
opening. No assumed intrabar stop fills, leverage, short sales or trading resume.

The opt-in execution option leaves default every-bar rebalancing and legacy
configuration hashes unchanged. The three definitions use explicit versioned
signal features evaluated by the shared DSL/evaluator. Signals use only their
known prefixes and strictly previous scheduled-session history. Holes, source
quarantines and short sessions invalidate history; unavailable sessions are
excluded explicitly, never scored as zero-return days. ORB relative-volume ranks
are known only after the first five completed bars across the conditional cohort.

Retain the unchanged minute gates, including their existing per-bar turnover
units and threshold. Do not relax the turnover gate to make low-frequency
strategies pass. A future cadence/turnover protocol needs its own reviewed
decision and cannot relabel these results. G7 stays false and TEST stays sealed.
The existing TRAIN-only model may be copied solely for evaluator lineage; these
are quantitative strategies and neither refit nor consume ML predictions.

Certification requires facts that the public OHLCV and daily reference files
do not contain: independent raw-minute vintage/units, causal publication and
receipt history, dated account-cost acceptance and executable liquidity/fill
calibration. The assessment must retain primary-source receipts and identify
missing evidence. Documentary rechecking cannot release quarantines or turn
missing evidence into a positive certificate. All old results remain immutable.

The initial bounded integration scope is three unchanged candidates on RELIANCE,
the complete frozen January 9–June 30, 2026 conditional VALID window, normal and
doubled costs, at most four isolated session workers. All three attempts are
preregistered before scoring, and all outcomes are retained. This scope is chosen
for integration coverage, not from a new profitability search. No claim of full
41-company shared-engine execution is made. The earlier 41-company TRAIN screen
remains separate. Market-hours PAPER scheduling and operational code are outside
this implementation change.
