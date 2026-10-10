# Trading persistence (step 097)

Migration `20261011_b41f09700500_005.py` follows revision `72ac7ed56ff4`.
The checklist originally called this migration 004; that number is already used
for experiment linkage, so existing history remains unchanged.

Run `alembic upgrade head` from the repository in the documented WSL environment.
The nine new tables are:

| Table | Purpose and references |
|---|---|
| strategies | Versioned alpha reference, parameters, code commit, runtime status |
| risk_limits | Scope/version, immutable limits JSON, unique SHA-256 hash |
| backtest_runs | Registered experiment, strategy, data snapshot, commit, config hash, seed, fill/cost references |
| orders | Client idempotency key, instrument/strategy/alpha references, exact quantities/prices, lifecycle timestamps, risk hash |
| fills | Exact execution values; composite order reference also verifies instrument and side |
| positions_snapshot | Scope/instrument/time key, quantity, cost and marked P&L |
| pnl_snapshots | Scope/time key; total reconciles realised + unrealised - fees |
| risk_events | Reason, severity, subject, risk limits hash, optional order reference |
| audit_events | Actor/action/subject/time and optional hashes/payload |

Money and quantities use NUMERIC(38,18), with non-finite values refused.
Event timestamps are integer UTC microseconds; administrative timestamps use
timezone-aware PostgreSQL timestamps. Referential deletes are restricted.
Orders require `is_simulated = true`; this migration cannot store live venue orders.
Risk limits, fills, position/P&L snapshots and audit events are insert-only using
the existing database trigger function. Order state and strategy status remain mutable.

This is persistence groundwork, not an implemented OMS, ledger, risk engine or
execution venue. Aggregate fill quantity checks and lifecycle transitions need the
later transactional runtime. Audit hash chaining is seventh-semester work; nullable
chain hashes do not claim tamper evidence. Time partitioning remains future work.
Backtest foreign keys establish experiment existence, while the future runner must
also verify that it is open before execution. These schema constraints do not prove
alpha promotion, complete result lineage or fill-to-market attribution by themselves.

Synthetic database tests roll back their rows. Migration downgrade removes these
nine tables and their contents; use it only when their data can be discarded.
