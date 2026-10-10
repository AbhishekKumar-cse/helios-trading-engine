# ADR-006: Core trading interfaces

| | |
|---|---|
| **Status** | Proposed; records the architecture section 8 contract for implementation |
| **Date** | 2026-10-11 |
| **Deciders** | Team lead approval not yet recorded |
| **Plan task** | 5H-01, step 098 (document); step 113 (Python Protocols) |
| **Replaces** | none; refines ADR-001 without changing the stack or simulated-only execution |

## Context

The quant DSL and ML models need to feed the same strategy/risk/OMS path. Paper
execution must later be replaceable by a simulated matching-engine cluster without
rewriting strategy logic. Architecture section 8 names five interfaces; this record
defines their inputs, outputs, ownership, ordering and failure behavior before the
shared record types and runtime components are implemented.

Existing batch feature/alpha evaluation and the gross/net simulator are research
implementations. They do not yet implement these event-driven contracts. This ADR
does not claim a running strategy, risk engine, OMS, venue or cluster.

## Decision

Use structural `typing.Protocol` contracts in Python, then equivalent typed
boundaries in C++ and Go. Preserve these logical operations across languages;
transport, wire encoding and deployment remain separate decisions. Avoid untyped
dictionary payloads across runtime module boundaries.

The signatures below retain the architecture's shape. Their named records are
contracts to implement in steps 107–113, not imports that already exist.

```python
class MarketDataSource(Protocol):
    def events(self) -> Iterator[MarketEvent]: ...

class AlphaModel(Protocol):
    definition: AlphaDefinition
    def value(self, fv: FeatureVector) -> AlphaValue: ...

class Strategy(Protocol):
    def on_update(self, alpha: AlphaValue, book: BookView, pos: Position,
                  open_orders: OpenOrders, risk: RiskState) -> list[OrderAction]: ...

class RiskEngine(Protocol):
    def check(self, action: OrderAction) -> RiskDecision: ...

class ExecutionVenue(Protocol):
    def submit(self, o: NewOrder) -> Ack | Reject: ...
    def cancel(self, c: CancelOrder) -> Ack | Reject: ...
    def amend(self, a: AmendOrder) -> Ack | Reject: ...
    def subscribe_reports(self, cb: Callable[[ExecutionReport], None]) -> None: ...
    def snapshot_open_orders(self) -> list[VenueOrderView]: ...
    def venue_info(self) -> VenueInfo: ...
```

### MarketDataSource

File replay, live market-data capture and synthetic SpoofBench sources expose the
same event iterator. Events carry source/instrument identity, sequence information,
exchange time and ingest time in integer UTC microseconds. Replay preserves recorded
ordering; it must not quietly sort, fill missing events or fabricate observations.
End of a finite replay is normal. Malformed data, sequence gaps and inconsistent
books must be surfaced explicitly so downstream availability can be invalidated.
Live market-data access does not authorize live order execution.

### AlphaModel

`definition` identifies the immutable registered alpha version, feature-set version,
horizon, output convention and provenance. `value` consumes only features available
at its decision timestamp and returns `AlphaValue` with status `OK`, `UNAVAILABLE`
or `STALE`, instrument/time and definition lineage. Warm-up, missing inputs or stale
inference are not represented as an apparently valid zero signal. ML predictions
must be explicitly mapped into alpha values, with model/checkpoint lineage retained.
The DSL's intermediate arithmetic stays raw; only the final alpha obeys its stored
output bounds. Fit/normalization and TEST access remain separate research controls.

### Strategy

`on_update` reads a consistent decision-time view of alpha, book, positions, open
orders and risk state, then emits requested actions. It cannot submit directly to a
venue or update authoritative fills/positions. Unavailable/stale alpha cannot create
new exposure; risk-reducing handling is governed by the later strategy/risk rules.
Actions distinguish new, cancel and amend requests and carry client identifiers and
the decision's lineage. A strategy exception must not produce an implicit order.

### RiskEngine

Every action passes through a synchronous inline `check`; no fire-and-forget risk
approval, override flag or direct strategy-to-venue route is permitted. Accept returns
an authorised order/action carrying the applied limits hash; reject carries a stable
reason code. Missing limits, stale required state or an internal error fail closed.
Risk owns authorization; OMS owns order lifecycle. A shutdown/kill-switch path must
remain operable independently of a hung strategy. Enforcing construction and routing
of authorised types is later runtime work; a Protocol alone does not prevent bypass.

### ExecutionVenue

OMS translates only authorised actions into the typed venue commands above.
Synchronous `Ack` means command acceptance, not a fill. Execution reports provide
subsequent acknowledgements, rejects, partial/full fills, cancellation and amendment
outcomes in order per order. Client order IDs are idempotency keys: retries must not
create additional exposure. Duplicate fills/reports must not double-count the ledger.
Timeouts have an unknown outcome and require reconciliation, not unconditional retry
under a fresh ID. `snapshot_open_orders` returns venue state for that reconciliation.

`venue_info` exposes venue identity/capabilities and `is_simulated = true` for both
the paper venue and future simulated cluster. Unsupported amend must return an explicit
reject. Never silently substitute a real exchange order endpoint. Paper fills cannot
claim a price better than the contemporaneous best contra price. Both venues will
share conformance tests for duplicates, ordering, partial fills and cancel/fill races.

### Boundary data and ownership

Keep **Feature → Prediction → Alpha → Signal → Strategy action → Order** distinct.
A model prediction is not already an executable order, and an accepted command is
not already a fill. Immutable records carry instrument, time and source/definition
lineage where relevant. Event-loop state owners update book, orders, positions and
P&L in deterministic order; callbacks must not introduce hidden asynchronous state
changes. C++ tick/lot integer units and Python research floats require explicit
conversion at the adapter, with parity tests before cross-language use.

## Alternatives considered

| Option | Benefit | Reason not selected |
|---|---|---|
| Concrete inheritance tied to one venue | Easy initial wiring | Couples strategy/risk to paper implementation |
| Async risk approval through a queue | Loose coupling | Violates the required inline fail-closed authorization boundary |
| One generic dict/message interface | Fewer initial record types | Hides availability, authorization and acknowledgement/fill distinctions |

## Consequences

Adapters can reuse strategy logic across replay, paper and the simulated cluster.
The cost is explicit types, state ownership and conformance tests; annotations alone
cannot provide safety. Steps 107–113 implement the records and Protocols; later risk,
OMS, paper venue and ledger steps enforce the behavior. Step 098 completes this
document only. No measured latency, live trading capability or runtime conformance
is claimed. Revisit with a new ADR if implementation needs a different operation
shape or cannot preserve deterministic ordering across adapters.

## References

- [Architecture sections 8 and 10](../../ARCHITECTURE_AND_TECH_STACK.md)
- [ADR-001: stack and simulated execution](ADR-001-tech-stack.md)
- [SRS sections 14, 16 and 22](../spec/HELIOS_SRS_and_System_Design_v1.md)
- [Sequential work order: 098, 107–113](../../5thSem/5thSem_Sequential_Steps.md)
