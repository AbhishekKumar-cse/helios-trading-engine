# Execution and accounting report (150)

Generate the report from the finished run's hash-verified saved evidence:

```bash
/home/abhi/.venvs/helios/bin/python scripts/report_backtest.py --run-id hand_20261015
```

The standalone HTML is `reports_out/backtests/hand_20261015/report.html`.
Generation does not rerun execution, fit models, load new market inputs or access
TEST. It verifies the registered artifact hash, source/config/snapshot lineage,
and database order/fill/P&L projections. Changed evidence refuses reporting.
Content-hashed HTML and JSON summary archives preserve each generated version;
`report.html` is the latest presentation only. Summaries retain full decimal
precision and report-generation commit/dirty state; HTML shows six decimals.

The report includes gross/net P&L, realized/unrealized P&L, explicit fees and
slippage, cash/equity, maximum drawdown and duration, exposure, orders/fills,
maker/taker split, turnover, risk rejects, unavailable signals, unexecuted tail
intents, per-coin accounting and fill details. Charts use recorded observations.
Gross removes fees and recorded opening slippage at the same actual fill sizes,
not a separately rerun no-cost strategy. Net includes both. This distinction
avoids claiming a hypothetical strategy would have traded the same quantities.

Net-equity drawdown includes initial capital. Its duration runs from a peak to
recovery or the last recorded close. Trade count means fill events, not completed
round trips. Turnover is actual traded notional divided by initial capital; it
is not the research gate's mean position change. Existing open inventory remains
marked at the declared bar-close proxy without a forced exit. The execution
model's queue, impact, partial-fill, latency and sensitivity limitations remain
visible. A single instrument per run is reported as its own coin attribution.

The completed synthetic demonstration (experiment **5302**, clean source
`8c24555c0967a1d2b1402ff6886901b79a156940`) persists three orders/fills and ten
position/P&L snapshots, all matching the independent CSV. Its artifact SHA-256 is
`9e47df8e46c810eadbfc831b85b8ae5d084a05d1ddc418fc6da356a9c0b2738b`.

| Synthetic accounting measure | USDT |
|---|---:|
| Gross before fees/slippage | 20.000000 |
| Slippage | 0.110000 |
| Explicit fees | 0.549978 |
| Net P&L | 19.340022 |
| Maximum drawdown | 50.000000 |
| Maximum gross exposure | 250.000000 |

These numbers verify a correctness fixture, not market profitability. The
original 22 research result rows and 12 definitions retain their hashes, and
their TEST counters remain zero. Proof is in
`reports_out/steps_146_150_verified.json`. Backtesting a real candidate remains
step 151 and is outside this batch.

Batch verification: 1,688 tests passed, one slow test deselected, with 15 existing
warnings. The final report recovery-duration check also passes in its five-test
suite; strict typing and repository lint/format checks pass. The generated HTML
was visually checked in the browser, including its narrow-panel chart layout.
