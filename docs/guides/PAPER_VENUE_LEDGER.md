# Bar paper venue and fill accounting

`helios.sim.paper.BarPaperVenue` implements `ExecutionVenue` for simulated modes.
It snapshots accepted fee settings and exposes their hash. `submit` returns only
command acceptance; `dispatch_reports` delivers ordered reports explicitly.
For existing OMS orders, first mark PENDING_NEW, use `submit_order` to preserve
the OMS identity, then dispatch reports into `oms.on_report`.

Deliver `BarOpen` after commands eligible at that opening have been submitted.
Market orders fill at the first observed opening at/after their decision time,
buy at open plus slippage and sell at open minus slippage, with taker fees on
executed notional. The bar scheduler makes close-t decisions eligible only at
the next opening; a late decision cannot act at an earlier opening. Submission
after an opening was processed cannot retroactively fill there. No closing-bar
high, low or close is passed to market execution.
OMS handoff uses the pending order's timestamp, including any delay after the
original decision. Commands, openings and completed bars advance one clock per
symbol; stale commands reject and backwards replay raises before state changes.
Identical retries return the original acknowledgement without advancing time.

Client retries preserve identity and never generate another fill; conflicting
payloads reject. Cancellation retains unfilled residual quantity. Amendment
returns UNSUPPORTED_AMEND. Numeric values round half-even to 18 decimal places;
unrepresentable values fail before a fill is applied. Quote currency is USDT.

This bar model assumes complete fills, unlimited liquidity and no market impact.
It does not model queues, volume participation or transport latency. It is not
the future L2 execution model. Session state is in memory; durable runner/order
persistence is later work.

Limits crossing strictly beyond the opening price execute as takers, with adverse
slippage capped at the limit. Equality alone never fills. Other GTC limits rest
for the following complete bar: BUY requires low strictly below the limit; SELL
requires high strictly above it, with positive volume. These fill at the limit
with maker fees. Call `on_bar` when that bar is observed, before its next opening.
Passive fills use the bar ingest time because OHLC does not identify a trade's
intrabar timestamp. Uncrossed IOC/FOK limits expire at the opening under the
full-liquidity assumption. GTC orders remain eligible on later bars until cancelled.

Complete a resting-order bar before processing another opening for that symbol.
An unresolved resting order can be cancelled at its opening boundary; a later
cancel is refused until `on_bar` resolves the range. This avoids guessing whether
an intrabar cancellation preceded a trade-through. Late submissions cannot use
the current bar's range. Zero-volume bars cannot produce passive fills.

`helios.sim.ledger.PnLLedger(initial_cash, mode)` owns one USDT accounting scope.
Send accepted fill reports to `on_report`, or fills to `book`; acknowledgements
and cancellations have no accounting effect. Identical fill retries are no-ops;
conflicting IDs, foreign modes/currencies and backwards clocks fail atomically.
Average cost follows SRS 24.5 for long/short opens, adds, reductions, flattening
and flips. Cash includes trade notional and fees; realized P&L excludes fees.
Exact rational cost basis avoids drift from repeating weighted-average decimals.
Public records round half-even to numeric(38,18); overflow is refused.

For `snapshot(timestamp, marks)`, supply a fresh, nonstale `BookView` for every
nonflat instrument at that exact timestamp. The declared mark is the two-sided
midpoint. Snapshot marking changes unrealized P&L only, never cash, realized P&L,
inventory or fees. Ledger config/mark/rounding policy is hash-bound. Initial cash
is fixed; deposits, withdrawals and non-USDT fee conversion are unsupported.

Every snapshot checks the exact internal identity:
`cash + signed inventory at mark = initial cash + realized + unrealized - fees`.
It also checks public rounded fields within an absolute 2e-18 USDT tolerance
(four independently rounded values). A mismatch logs CRITICAL
`LEDGER_RECONCILIATION_BREAK`, raises `ReconciliationError`, and latches a halt
on subsequent reporting and fill booking. There is no automatic reset.
The property test uses 150 generated multi-instrument sequences and an
independent cash-flow/inventory model, including 18-decimal quantities, shorts,
position changes and duplicate retries. Fault injection checks the halt latch.
