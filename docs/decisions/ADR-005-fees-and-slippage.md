# ADR-005: Trading fees and slippage assumptions

| | |
|---|---|
| **Status** | Accepted (2026-09-20, approved by team lead) |
| **Date** | 2026-09-20 |
| **Deciders** | Abhishek Kumar (team lead) |
| **Plan task** | 5A-12 (step 035) |
| **Replaces** | none |

## Context

An alpha that looks profitable **before** costs can easily lose money **after** them, so every
metric in HELIOS is reported net of costs (QNT-006, ALG-028). The simulator (step 096), the
backtester (step 142) and the paper venue (step 141) all need the same, pre-committed cost
numbers, recorded with the date they were checked, so nobody can lower costs later to make a
result pass the gates.

**Binance spot fees, checked 2026-09-20** on the official fee schedule
(https://www.binance.com/en/fee/schedule):

| Tier | Maker | Taker |
|---|---|---|
| Regular user (VIP 0) | 0.100 % (10 bps) | 0.100 % (10 bps) |
| Regular user paying fees in BNB (25 % off) | 0.075 % (7.5 bps) | 0.075 % (7.5 bps) |

*1 bps (basis point) = 0.01 %.*

## Decision

### 1. Fees: VIP 0 without the BNB discount

| | Maker | Taker |
|---|---|---|
| **All 5 coins** (BTC, ETH, SOL, BNB, XRP / USDT) | **10 bps** | **10 bps** |

We assume the plain regular-user tier. HELIOS trades on paper and holds no BNB, and a
new account starts at VIP 0, so the discount is not guaranteed.

### 2. Slippage (assumption, not measured)

Slippage is the difference between the price we assume and the price a real order would get
(half the bid-ask spread plus small market impact). Applied **per side** to every market
order (fills at the next bar's open ± slippage):

| Coins | Slippage per side | Why |
|---|---|---|
| BTCUSDT, ETHUSDT | **2 bps** | Most liquid pairs, very tight spreads |
| SOLUSDT, BNBUSDT, XRPUSDT | **5 bps** | Less liquid, wider spreads |

Limit orders (5th-sem paper venue) pay the maker fee and **no** slippage, but only fill when
the next bar trades **through** the limit price (step 142).

### 3. Cost used by the alpha simulator

The simulator (step 096) treats every position change as a taker trade:

```
cost_bps (one side) = taker fee + slippage
cost_t = turnover_t × cost_bps / 10,000
```

| Coins | One side | Round trip (buy + sell) |
|---|---|---|
| BTC, ETH | 10 + 2 = **12 bps** | 24 bps |
| SOL, BNB, XRP | 10 + 5 = **15 bps** | 30 bps |

Example: an hourly BTC alpha with turnover 0.30 per hour pays
0.30 × 12 / 10,000 = **0.00036** (0.036 %) of capital in costs every hour.

### 4. Robustness (already in the gates)

- Every result shows a **cost-sensitivity curve** at 0.5×, 1×, 2×, 3×, 4× these costs (step 104).
- Gate **G6** requires Sharpe > 0 at **2×** cost; `cost_stress_sharpe` is reported (ADR-002).

### 5. Where the numbers live

`configs/fees.yaml` (step 036), with `checked_on: 2026-09-20` and the source URL.
Every result records the config hash. **Changing a fee or slippage value needs a new ADR**,
and old results keep their old costs.

## Alternatives considered

| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| **A: 10 bps fee + 2/5 bps slippage (chosen)** | Conservative, matches a real new account | May slightly overstate costs | — |
| B: 7.5 bps (BNB discount) | Closer to what active traders pay | Requires holding BNB; flatters results | Kept as a sensitivity case (0.5×–4× sweep covers it) |
| C: Zero slippage | Simplest | Unrealistic; inflates every alpha | Audit A-30: costs must never be omitted |
| D: One slippage value for all coins | Simpler | Ignores the liquidity difference between BTC and XRP | Per-coin values are just as easy |
| E: Measured slippage from order-book data | Most accurate | Needs L2 data for all coins and years | Planned for the 6th semester; this ADR is the 5th-sem assumption |

## Consequences

- **Good:** costs are fixed before any result exists; results are conservative; the same
  numbers drive the simulator, backtester and paper venue.
- **Bad / costs:** slippage values are **assumptions**, not measurements; minute alphas with
  high turnover will be hit hard (which is realistic).
- **Follow-up work:** `configs/fees.yaml` (step 036); cost model (step 096); cost sweep (step 104);
  paper venue fees (steps 141–142); compare assumed vs paper-trading costs (step 170).
- **How we will know it was wrong:** if paper-trading fills (step 170) or 6th-semester
  order-book data show real slippage clearly above or below these values, write a new ADR.

## References

- Binance fee schedule, https://www.binance.com/en/fee/schedule (checked 2026-09-20)
- `docs/spec/HELIOS_SRS_and_System_Design_v1.md`: §20.4 (costs and slippage), QNT-006, ALG-028, audit A-30
- ADR-002 (G6 and `cost_stress_sharpe`)
