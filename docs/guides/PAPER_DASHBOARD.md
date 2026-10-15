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
