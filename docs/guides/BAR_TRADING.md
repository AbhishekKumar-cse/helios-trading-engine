# Bar trading components

## Decision clock (121)

`BarEventLoop.run(source, decide, act)` constructs a historical timeline from the
typed source. Completed bars are delivered to `decide` at ingest availability;
intents can reach `act` only at a subsequent bar's opening, at or after that
decision clock. Equal-time closes precede opens, with symbol ordering. Delayed
ingest cannot cause retroactive execution. Opening callbacks receive `BarOpen`
(symbol, timestamp, opening price and snapshot), never future OHLC fields.

The loop rejects gaps, incomplete intervals, inconsistent snapshots, backwards
source ordering, duplicate command identifiers and mismatched intent lineage,
clock, symbol or mode. Unexecuted tail intents are returned. It materializes the
historical timeline; it is not a live streaming clock. `act` is an intent handoff,
not a fill. A caller must route through risk and OMS before any simulated venue;
those concrete execution and ledger components remain later checklist steps.

## Target allocation (122)

`target_notional(alpha, TargetConfig(capital=..., max_weight=...))` returns a signed
per-coin target equal to capital times maximum weight times bounded alpha. Capital
must be positive and weight in (0, 1]. Stale/unavailable alpha returns no target,
not a zero target. Exact Decimal arithmetic rounds toward zero at 18 decimal
places. Negative targets describe simulated short exposure; this allocation alone
does not authorize shorting or approve portfolio gross exposure.
