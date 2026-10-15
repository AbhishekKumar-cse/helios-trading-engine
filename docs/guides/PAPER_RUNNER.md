# Public minute PAPER runner (160)

`scripts/run_paper.py --run-id <fresh_id> --seconds 240 --endpoint spot443`
runs a bounded session from clean Git source. Apply Alembic migration 008 first.
Every session has a fresh directory under `reports_out/paper`, an immutable
initial identity manifest, a pre-observation infrastructure experiment, a unique
strategy/risk scope and a PAPER database run. Existing directories/IDs are never
reused. All observations, failures, orders, reports and reconciled snapshots are
retained. The final artifact hashes the initial manifest and observation log.

The stream ID hashes the initial session identity; it is explicitly not a claim
that future market bytes are already known. The final observation SHA-256 pins
those bytes. This namespace is separate from the immutable historical research
data snapshots. No TEST split or research evaluation is invoked.

The fixed integration policy is registered `minute_h04` version 1, one-bar
reversal. It was **REJECTED** on VALID. Its use here tests system integration
only; it is not a promotion or candidate selection. The existing feature runner
and DSL process two consecutive observed closed bars; the first signal is
explicitly UNAVAILABLE. No history is backfilled. The shared `BarStrategy`,
`DailyRisk`, `OrderManagementSystem`, `BarPaperVenue` and `PnLLedger` are the same
classes used by backtests. PAPER capital is 1,000 USDT with a 1% target weight,
30-USDT order cap, 20-USDT position/gross cap and 5-USDT daily loss guard.

The live fill policy is `later_received_public_price_proxy_v1`: after an intent
is submitted, a fresh in-progress update from the following minute provides a
public last-price proxy at its receipt clock. The existing venue applies its
full market-fill, accepted fee and slippage arithmetic. A delayed completed
bar's opening price cannot fill that intent. Public prices and marks are
labelled `public_last_price_proxy`; they are not observed bid/ask quotes. There
is no liquidity/queue/impact or spot-borrow model. Passive orders are unsupported.
Historical backtest execution semantics are unchanged.

Disconnect, missing/out-of-order closes, stale/skewed observations, clock
regression and expired intents stop the PAPER session, durably latch the shared
kill control and cancel accepted simulated pending orders. A bounded normal stop
also latches risk and cancels pending intents. Existing paper positions remain
recorded; no invented liquidation price is supplied. Restart requires a fresh
scope; unattended restart reconciliation and deployment are later work.

Orders/fills and P&L/position snapshots are checkpointed during the run. Fills
and snapshots remain append-only. `paper_run_id` owns these rows separately
from `bt_run_id`; fills inherit the order's ownership. Migration 008 enforces
PAPER mode, simulated execution, clean lineage and immutable terminal session
evidence. The finished strategy is HALTED. Inspect ownership with:

```sql
SELECT p.paper_run_id, p.mode, p.status, o.order_id, o.status, o.is_simulated,
       f.fill_id, f.price, f.qty, f.fee
FROM paper_runs p
LEFT JOIN orders o USING (paper_run_id)
LEFT JOIN fills f USING (order_id)
ORDER BY p.created_at, o.ts_created;
```

Runtime tests cover delayed fill timing, exact shared costs/accounting, explicit
unavailability, stale/gap/clock/intent guards, cancellation, mode refusal and
incremental PostgreSQL persistence. Matplotlib is now a base dependency because
the minute cost and ML pipeline CLIs generate required plot artifacts.
