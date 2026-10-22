# NSE PAPER ownership, kill and crash recovery

The public-data runner remains an integration test of a registered rejected
formula. It never routes orders to a broker or establishes candidate eligibility.
ADR009/010 gates, source exclusions, cost scenarios and sealed TEST are unchanged.

The runner now creates `nse_paper_session_v2` identities and holds an exclusive
PostgreSQL session advisory lock for its entire lifecycle. A second runner or
recovery process using another database connection cannot own the same scope.
The connection stays checked out; process/connection death releases ownership.
The runner checks that retained connection before and after public reads; a lost
connection cannot transparently reconnect and continue without ownership.
Use the same database and session directory for recovery. Old v1 sessions had no
ownership lease and are deliberately refused by this recovery command.

The dashboard kill command accepts both validated crypto and equity PAPER configs.
It retains the atomic kill event and operator audit, with matching config hash.
The NSE loop checks the durable trip before and after each blocking public read,
even when no quote arrives or no order is pending. A read can block for up to the
existing 15-second HTTP timeout; this is a software polling bound, not a measured
market-hours cancellation latency or an independent process supervisor. Risk
also rechecks the durable kill before creating an order or filling a pending one.

At startup, old completed candles are explicitly logged and skipped without
changing their timestamps. The first fresh close must arrive within one minute
plus the existing five-second skew budget. After startup, a five-second receipt
silence or clock regression trips risk and cancels pending simulated intents.
Stale provider event times and quote-before-intent remain terminal failures.
These are the strict profile's limits; a public feed that cannot meet them fails
strict acceptance. That result is retained even if a separate delayed simulation
is subsequently requested.

Under [ADR019](../decisions/ADR-019-delayed-public-paper.md), the explicit
`--timing delayed_public` option permits a separately labelled simulation with
120-second maximum data age and 180-second pending-intent expiry. Strict mode
remains the default. Decisions keep their real receipt time. Older quotes never
fill newer orders: the runner waits for a provider trade timestamp after order
creation, with no backdating or candle-close fills. Candle age and intent expiry
are checked independently even when another feed keeps responding. Future-clock
tolerance stays at most five seconds. Identity, gap, ownership, kill, risk and
recovery controls remain active. Output is labelled delayed-public simulation
and cannot close strict-feed or promoted-trial acceptance.

In the documented WSL environment, run a bounded integration session during an
actual normal NSE session, using a unique run ID and the retained official raw
calendar. Clean source and registered whole-share INR instrument metadata are
required by the existing reported-run contract:

```bash
python -m helios.equities.paper_runner \
  --run-id nse_paper_unique_session \
  --calendar data/equities/nifty50_minutes/20261017_public_round1/nse_holidays_raw.json \
  --seconds 900
```

Fifteen minutes allows several genuinely observed closes for feature warmup.
Provider denial, stale timestamps or missing observations may end the run earlier.
Retain `session.json`, raw receipt journal, artifact, fills, positions, P&L and
risk/audit events. An end-of-session kill cancels intents; it does not manufacture
an exit fill for an existing position. Check the artifact for non-flat inventory.
The legacy PAPER 15+5bps per-side scenario remains explicit; BACKTEST v2 reference
tax settlement is not represented as a PAPER account contract-note calculation.

After an unexpected process exit, recover its original scope:

```bash
python -m helios.equities.recovery \
  --run-id nse_paper_unique_session --actor local_operator
```

Recovery checks the session/config identity and exclusive ownership, then latches
the kill. It reconstructs the INR ledger from durable simulated fills, verifies
order conservation and every stored P&L/position checkpoint, and cancels pending
intents belonging to the dead in-memory venue. It retains a hashed recovery
artifact and operator audit, marks the old scope failed and its experiment
abandoned, and leaves the strategy halted. Mismatches are retained as `MISMATCH`;
they never permit resumption. Fills and historical accounting rows stay unchanged.

Recovery **does not resume trading or reset capital/inventory**. A recovered
non-flat position remains visible in the artifact at its historical mark. There
is no current broker account to reconcile or executable exit quote. A subsequent
run is a separately labelled integration scope, not a continued account or a
seven-day trial. Never combine independent balances into a continuous P&L series.

Database changes and audit commit together. If that transaction fails, a written
recovery JSON may remain orphaned. Only an artifact whose path and hash match the
terminal database row proves a committed recovery; retain orphan evidence and
retry with a new artifact name. Recovery does not overwrite an earlier artifact.

Run `scripts/check_nse_paper_readiness.py --calendar ... --output ...` for a
read-only preflight. It records actual clock/calendar/source readiness and zero
observations. It never claims market-hours acceptance or elapsed trial time.

Actual acceptance still requires: fresh public feeds during an open session;
observed fill lineage; operator kill with zero subsequent orders/fills; a real
process stop/recovery with matching durable inventory; and measured outage and
restart behavior. Rolled-back synthetic database tests establish implementation
behavior only. Sunday/off-hours checks cannot close steps166/167/170/174.
