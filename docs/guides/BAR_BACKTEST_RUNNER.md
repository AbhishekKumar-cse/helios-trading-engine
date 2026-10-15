# Config-driven bar backtests (149)

Use the documented WSL environment and migrate the database to revision
`d14900000700` (additive migration 007). From clean committed source:

```bash
/home/abhi/.venvs/helios/bin/alembic upgrade head
/home/abhi/.venvs/helios/bin/python scripts/run_backtest.py \
  --config configs/backtests/hand_scenario.yaml --preregister
```

This single command registers the exact config as a BACKTEST experiment before
execution, then runs the fixed synthetic ten-bar correctness fixture once. Its
run ID is `hand_20261015`. It creates an explicitly synthetic snapshot/definition
without altering the research alphas. The CSV checksum and path determine the
snapshot ID. The instrument must already exist. The output JSON under
`reports_out/backtests/` retains the bound config/experiment, clean source,
snapshot, seed, input hash, typed bars/signals, orders, reports and reconciled
position/P&L snapshots. It declares BACKTEST and simulated execution explicitly.

The run uses the shared BarStrategy, DailyRisk, OMS, BarPaperVenue, PnLLedger and
BarEventLoop. Risk checks run at decision time and again at the eligible opening;
OMS also requires fresh authorization. Only fills book accounting. Daily losses
and manual/persisted halts remain latched. Each snapshot checks reconciliation.
Tail intents lacking another opening remain explicitly unexecuted; no forced
liquidation is added. Missing signals remain UNAVAILABLE, never substituted zeros.

`backtest_runs` reserves the unique ID before inputs load. Strategies and immutable
risk limits bind the run's scope. Orders and position/P&L snapshots carry a run FK;
fills inherit ownership through their orders. Actual results commit in one
transaction. A failure rolls back those orders/fills/snapshots and retains a failed
attempt plus any separately committed safety trips. Finished/failed run metadata
is protected by a database trigger; artifact checksums detect changed files.
Preregistration, experiment status and run IDs prevent automatic retries/overwrites.
Do not rerun the completed config. A genuinely new experiment needs a new run ID
in the top-level config and its strategy/risk scopes, with explicit preregistration.

The runner supports one instrument per accounting scope. `registered_hourly`
inputs replay snapshot-verified bars and checksum-verified feature exports, with
registered expression or supported frozen ML alphas. Configured ranges must stay
inside TRAIN or VALID. TEST is refused during config validation before input
access; there is no TEST budget bypass. Incomplete/gapped bars refuse execution.
The fixed demo is synthetic; it does not select or backtest a real candidate
(step 151 is separate). A finished execution is not an alpha gate/promotion result.

Marking is explicitly **bar_close_proxy**, hash-bound in config and ledger policy.
Reference prices expressed as symmetric BookViews are not observed midpoint quotes.
The fill model assumes complete next-opening market fills, accepted per-side
slippage and maker/taker fees. Queueing, impact, partial fills and transport latency
are unmodelled. Future L2 simulation and fill/latency sensitivity are separate work.

Tests compare the production runner to the fixed independent CSV and verify
determinism, chronological/split boundaries, unavailable signals, source checksums,
durable ownership, terminal immutability, kill latching and atomic failure recovery.
Database test transactions roll back; only the explicit clean-source command
creates the retained synthetic demonstration.
