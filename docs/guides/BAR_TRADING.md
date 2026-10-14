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

## Rebalance intents (123)

`BarStrategy` implements the shared Strategy protocol. Its reference price is the
current bid/ask midpoint. Target base quantity minus current position and signed
remaining working orders determines the requested change. Pending cancellation
still counts until confirmed. Changes smaller than capital times
`rebalance_threshold` produce no order; equality is actionable. Decimal quantities
round toward zero at 18 places. Same inputs produce the same command ID, including
the strategy configuration, alpha lineage and sorted working orders.

Stale/unavailable alpha, halted/missing-limit risk state, stale or missing quotes,
future state and inconsistent decision timestamps produce no order. Mismatched
symbols/mode/snapshot or duplicate working orders are errors. Commands preserve
alpha lineage and request simulated MARKET/IOC execution; this strategy neither
authorizes an action nor modifies positions. Gross portfolio risk and instrument
constraints belong to the subsequent risk implementations.

## Ordered risk framework (124)

`CheckChain(tuple_of_RiskCheck, state_provider)` implements synchronous
`RiskEngine.check`. Each check returns `None` to continue or a rejection
`ReasonCode` to stop. The first rejection wins; later checks never run. All-pass
returns the exact action wrapped with the current limits hash. An empty chain,
missing limits, halted state or state older than the command cannot authorize it.
Provider/check exceptions and malformed return values reject with INTERNAL_ERROR,
without exposing private exception text. State is read and validated once per
decision. Checks must be distinct, ordered and named.

This framework requires callers to install the concrete checks. It does not
replace the later instrument, size, price-band, projected position, exposure,
daily loss or kill-switch implementations. No permissive production chain is
constructed here; successful fixture checks demonstrate only framework behavior.

## Order size and price band (130)

`SizePriceRisk` implements inline checks bound to a hash of immutable per-symbol
`SizePriceLimits`. State must identify that exact limits snapshot. Each invocation
reads and validates the state once and the price history once. History must be
unique, chronological, already available, fresh, long enough for the configured
median window, and from the action's symbol/snapshot. Unknown instruments, missing
limits, stale data and internal provider errors fail closed with stable reasons.

Maximum order notional is quantity times the larger of the requested limit price
and latest available reference price; MARKET uses the latest reference. AMEND uses
its new total quantity conservatively. Equality at the limit passes. The next
check requires price inside median times (1 ± configured fraction), inclusively;
LIMIT/AMEND use their requested price and MARKET uses the latest reference. The
median uses the last configured number of available observations, not future bars.
Cancels require the matching limit snapshot but no price history, since they add
no exposure. Existing halted-state guards still apply.

This adapter covers size/price checks, not portfolio position, gross exposure,
daily loss, kill switch or OMS lifecycle. Those are later steps. It creates no
fills and records no fabricated market observations. Tests cover threshold edges,
market spikes, amend quantities, incomplete/future/stale history, hash binding,
first-failure ordering and single-read consistency.

## Projected portfolio limits (131)

`PortfolioRisk` adds per-instrument position caps and a gross exposure cap after
the size/price checks, bound to the complete immutable `PortfolioLimits` hash.
For each coin it considers both bounds of current quantity plus possible remaining
BUY and SELL fills. Opposing orders cannot offset each other before they fill;
pending cancellation still counts. The worst absolute bound is marked using the
available price, conservatively using the larger requested price for the target.
Gross exposure sums absolute worst-case notionals across coins.

The 1,800 current + 150 working + 200 new example exceeds 2,000 and is rejected;
equality passes. AMEND replaces the original remaining quantity with new total
minus already filled quantity, rather than counting both versions. Unknown or
invalid amend targets are rejected. One portfolio snapshot supplies positions,
orders and marks for both checks; missing, future, duplicated or mismatched
snapshot state fails closed. Existing over-limit exposure cannot be assumed to
disappear because an offsetting order has merely been requested. Cancels add no
exposure. No fills, position updates or performance observations are created here.
