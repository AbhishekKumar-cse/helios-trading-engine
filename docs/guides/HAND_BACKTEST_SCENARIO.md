# Ten bars and three fills (147–148)

The fixed spreadsheet export is
`research/tests/fixtures/backtest/ten_bars_three_trades.csv`. Every row is a
synthetic hourly BTCUSDT bar, followed by its expected post-close accounting.
It is a correctness fixture, never market data or a profitability observation.
The CSV contains fixed decimal expectations, independently calculated in a
spreadsheet before the execution test was written. Test code must never generate
or overwrite these expected values from the venue/ledger implementation.

Assumptions: 1,000 USDT initial cash, 500 USDT maximum target notional (capital
times 0.5 max weight), zero rebalance threshold, market IOC orders, accepted
BTC slippage 2 bps per side and taker fee 10 bps on executed notional. Midpoint
marks in this synthetic fixture equal each bar's close. There is no final forced
liquidation. The final short remains marked, with unrealized P&L separate.
Here “three trades” means three order fills, not three completed round trips.

The decision at bar 0 close has alpha 0.2: target 100 / close 100 = +1 coin.
At bar 3, alpha 0.48 targets 240 / close 120 = +2 coins, adding one.
At bar 6, alpha -0.2 targets -100 / close 100 = -1 coin, selling three.
Blank alpha cells mean UNAVAILABLE and produce no new intent. None of these
decisions may fill in its own bar.

| Fill bar | Action | Execution calculation | Fee calculation |
|---|---|---|---|
| 1 | BUY 1 | 100 × 1.0002 = 100.02 | 100.02 × 1 × 0.001 = 0.10002 |
| 4 | BUY 1 | 120 × 1.0002 = 120.024 | 120.024 × 1 × 0.001 = 0.120024 |
| 7 | SELL 3 | 110 × 0.9998 = 109.978 | 109.978 × 3 × 0.001 = 0.329934 |

After the second fill, average entry = (100.02 + 120.024) / 2 = 110.022.
The third fill closes two long coins: realized P&L = 2 × (109.978 − 110.022)
= -0.088. The remaining one-coin short has cost 109.978. At final mark 90,
unrealized P&L = 109.978 − 90 = 19.978, and total fees = 0.549978.

Final cash = 1,000 − 100.02 − 0.10002 − 120.024 − 0.120024
+ 329.934 − 0.329934 = **1,109.340022**.
Final equity = cash − 1 × 90 = **1,019.340022**.
Net P&L = -0.088 + 19.978 − 0.549978 = **19.340022 USDT**.
All ten cash/equity/position/average-cost/P&L rows reconcile independently.
The CSV records six decimal places because these chosen inputs yield terminating
values at that precision. The implementation comparison uses exact Decimal
equality against the project's 18-place record boundary, with no float tolerance.

Step 148's `test_hand_backtest.py` passes only the input columns to the real
BarStrategy, DailyRisk, OMS, BarPaperVenue and PnLLedger through BarEventLoop.
Every saved expected field and fill is compared exactly. Changing a later bar
cannot change earlier reports or accounting. Optional `opened`/`closed` clock
callbacks let the venue see each opening and resolve completed ranges before
the next decision, without exposing that bar's high/low/close at the opening.
The test is in memory; config-driven database persistence follows in step 149.
