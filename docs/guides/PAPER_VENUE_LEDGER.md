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
