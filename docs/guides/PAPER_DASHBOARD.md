# Local PAPER dashboard

Run the Streamlit command in [REGISTRY_DASHBOARD.md](REGISTRY_DASHBOARD.md), bound
to `127.0.0.1`, and select **Paper trading** in the sidebar. All sessions are
explicitly labelled **PAPER / is_simulated = true**. Integration sessions can use
a rejected candidate; their presence does not imply promotion or real execution.

The page refreshes uncached PostgreSQL checkpoints every two seconds while its
browser session is active, using a [Streamlit fragment](https://docs.streamlit.io/develop/api-reference/execution-flow/st.fragment).
Each read uses a repeatable-read, read-only transaction. Select any retained PAPER
session; backtest ownership is excluded. It shows the latest net/realised/unrealised
P&L and fees, latest position per instrument, working orders, frozen risk limits
and durable kill state. P&L comes from the ledger checkpoint, not recomputation
from dashboard prices. Decimal accounting is displayed without rounding to float.

No checkpoint means unavailable, never zero. Checkpoint UTC time and age are
visible; a running session older than ten seconds is flagged stale. `running`
is a persisted lifecycle status, not proof that a feed/process is alive. Completed
sessions display historical positions, including positions retained on shutdown.
ARMED means the durable kill latch is absent; it is not a claim that every order
passes the other risk checks. Connection failures hide exception/settings details.

Step 161 validation: PostgreSQL fixture moves through empty, pending and filled
checkpoints; the view follows updates without mixing backtest rows. Streamlit
AppTest covers page navigation, unavailable values, stale warnings and badges.
Existing registry and spawned-worker regressions remain applicable. Rendering
and database reads only occur when explicitly invoked by guarded `main()`.

## Local halt control (162)

Running PAPER sessions offer **Halt this PAPER session**, with a required local
operator name and justification. These are operator-supplied audit labels, not an
authenticated identity; keep the app bound to loopback. Terminal sessions have
no control, and the server rejects unknown, backtest and terminal run IDs even
if the display is stale. No reset or limit-edit control is provided.

The handler locks and validates the running PAPER session/configuration, then
uses the existing shared durable kill primitive. Each newly latched trip writes
one `risk_events` row and one hash-bound `KILL_SWITCH_TRIPPED` audit row in the
same transaction. This also covers future daily-loss and runner trips through
that primitive; historical events are not backfilled. Every accepted dashboard
request additionally records `PAPER_KILL_REQUEST`, including justification and
whether the scope was already halted. Repeated presses do not duplicate trips.
Audit failure rolls back the control transaction; the UI never confirms success
before commit. Request audit rows are append-only; journal-wide hash chaining is
not implemented by this change.

The risk engine checks the durable scope on order authorisation. A pending
simulated intent is cancelled before a later price can fill it, when the runner
next processes data (or during bounded shutdown). This does not flatten an
existing position or guarantee a stalled runner has processed cancellation.
The view follows persisted order/risk updates on its next two-second refresh.

Verification presses the actual Streamlit form against a transactional PostgreSQL
fixture with the real risk/OMS/venue stack: new intent rejected HALTED, pending
intent cancelled, zero fills. Other cases verify repeat-request idempotence,
required operator fields, terminal/foreign-scope rejection, and atomic rollback
when the audit insert fails. Fixture rows are rolled back after each test.
