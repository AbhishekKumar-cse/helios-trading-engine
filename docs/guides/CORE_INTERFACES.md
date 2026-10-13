# Shared Python boundaries

## Event and command records (112)

`helios.common.types` supplies frozen Pydantic records with forbidden extra fields.
Nested collections are tuples; unavailable features and non-OK alpha values carry
None rather than an actionable zero. Times are non-negative int64 UTC microseconds,
sequence numbers are non-negative integers and decision lineage retains alpha
version, feature-set version, family, commit, config, snapshot, seed and optional
model hash. Bar close_time is the exclusive end; ingest cannot precede that end.

Prices, quantities, position and P&L money use finite Decimal values within the
existing database numeric(38,18) domain. These are base/quote units, not C++ ticks
or lots. Adapters must convert explicitly. Filled plus remaining equals total
order quantity using an independent precision context, including partial fills.
State-dependent quantity checks and fill/report association are validated.
OrderState.CREATED/ACCEPTED serialize as NEW/ACK to match migration 005; no
migration or older database evidence is rewritten.

OrderAction is a discriminated union of NewOrder, CancelOrder and AmendOrder.
Amend quantity means new total quantity, not remaining quantity. A limit order
requires a price; a market order has no limit price. Each strategy request retains
lineage and BACKTEST/REPLAY/PAPER mode. LIVE is absent. RiskDecision acceptance
requires an AuthorisedOrder with an exact limits hash and ACCEPTED reason;
rejection carries no authorised action. VenueInfo explicitly requires simulated
execution. Constructing a record alone does not provide risk authorization:
later risk/OMS routing owns and enforces that boundary.

Supporting records include FeatureVector, BookView, RiskState, Ack and Reject.
OpenOrders is an immutable tuple of Order; VenueOrderView is the same immutable
read representation. MarketEvent currently aliases Bar for the fifth-semester
bar path, without claiming implemented LOB events. ADR-006 remains Proposed;
these types implement the existing architecture shape without inventing approval
or claiming a running strategy, risk engine or venue.
