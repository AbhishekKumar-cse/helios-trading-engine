# ADR-003: Horizon families and daily-aggregated Sharpe

| | |
|---|---|
| **Status** | Accepted (2026-09-20, approved by team lead) |
| **Date** | 2026-09-20 |
| **Deciders** | Abhishek Kumar (team lead) |
| **Plan task** | 5A-12 (step 033) |
| **Replaces** | none |

## Context

HELIOS builds alphas step by step on faster data: **hourly → minute → second → millisecond**
(ADR-001, OPEN-03). The same metric means very different things on different horizons:

- A Sharpe ratio is annualised with `sqrt(periods_per_year)`. An hourly alpha has
  8,760 periods per year, a minute alpha 525,600. Comparing a Sharpe computed on
  252 trading days with one computed on 525,600 minutes is meaningless (audit **A-01**,
  spec §19.6, requirement **SIM-005**).
- Crypto trades **24 hours a day, 365 days a year**, so the stock-market convention of
  252 trading days does not apply.
- Gate G3 (1 % < Turnover < 70 %) only has a clear meaning once "per what period" is fixed.

These rules must be fixed before the simulator (steps 095–108) computes its first metric.

## Decision

### 1. Horizon families

Every alpha declares one horizon family when it is registered. It never changes; a
different horizon means a new alpha.

| Family | Decision interval | `periods_per_year` | Data | Used in |
|---|---|---|---|---|
| **H-HOURLY** | 1 hour | **8,760** (24 × 365) | Binance 1h klines | 5th semester |
| **H-MINUTE** | 1 minute | **525,600** (24 × 60 × 365) | Binance 1m klines | 5th semester |
| H-SECOND | 1 second | 31,536,000 | 1s klines + trades | 6th semester (defined now, used later) |
| H-MICRO | 100 ms | 315,360,000 | Bybit L2 order book | 6th–7th semester (defined now, used later) |

- The year is **365 days** (leap days ignored), because crypto never closes.
- Timestamps and day boundaries are **UTC**.

### 2. Metrics inside a family (gates G1–G3)

- **Sharpe (G1) and Fitness (G2):** computed on per-period net P&L and annualised with the
  family's `periods_per_year`, exactly as in ADR-002.
- **Turnover (G3):** mean |Δposition| **per decision period** of the family
  (per hour for H-HOURLY, per minute for H-MINUTE).
- Gate results are compared **only between alphas of the same family**.

### 3. Daily-aggregated Sharpe (every result, every family)

Every `AlphaResult` also reports a **daily-aggregated Sharpe**:

1. Sum the net P&L of all periods within each **UTC calendar day**.
2. `daily_sharpe = mean(daily P&L) / std(daily P&L) × sqrt(365)`.
3. Days with **no data at all** are left out (never filled with zero). Days with gaps are
   kept but flagged, using the gap report from step 048.
4. If fewer than **30 days** are available, `daily_sharpe` is reported as **N/A**.

The daily-aggregated Sharpe is the **only** number used to compare alphas across families,
e.g. "is the best minute alpha better than the best hourly alpha?".

### 4. Recorded with every result

`horizon_family`, `periods_per_year`, the per-period Sharpe, `daily_sharpe` and the number
of days used. These go into the alpha registry (step 061) and the result lineage.

## Worked example

Same (made-up) alpha idea, run on two horizons:

| | H-HOURLY | H-MINUTE |
|---|---|---|
| Mean net P&L per period | 0.00020 | 0.0000040 |
| Std of net P&L per period | 0.0060 | 0.00080 |
| Per-period Sharpe = mean / std | 0.0333 | 0.0050 |
| × sqrt(periods_per_year) | × 93.59 | × 724.98 |
| **Annualised Sharpe (G1)** | **3.12** | **3.62** |

The minute version looks better on its own scale. But gate numbers from different families
are not comparable (autocorrelated minute returns inflate `sqrt`-scaling). Only the
daily-aggregated Sharpe of each, computed the same way from UTC-day P&L, may be compared.
*(Illustrative numbers only; no real result is implied.)*

## Alternatives considered

| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| **A: family-annualised gates + daily Sharpe for comparison (chosen)** | Follows spec §19.6 and SIM-005; ADR-002 unchanged; fair cross-horizon comparison | Two Sharpe numbers per result | — |
| B: 252 days per year (stock convention) | Familiar from papers | Wrong for a 24/7 market; understates periods | Crypto never closes |
| C: Use only daily Sharpe everywhere, including gates | One number | Too few data points for short minute test periods; would change ADR-002 | Keep gates per family |
| D: One Sharpe for all horizons, no family tag | Simplest | Meaningless comparisons (audit A-01) | Rejected by the spec |

## Consequences

- **Good:** every metric has one exact meaning; hourly and minute alphas can be compared
  honestly; the same rules extend to second and millisecond data later.
- **Bad / costs:** each result stores extra fields; minute test periods need at least
  30 days for `daily_sharpe`.
- **Follow-up work:** `configs/splits.yaml` and `configs/gates_v1.yaml` carry the family
  (step 036); metrics implement both Sharpe values (steps 100–101); the registry stores
  `horizon_family` and `periods_per_year` (step 061).
- **How we will know it was wrong:** if per-period and daily Sharpe regularly disagree in
  sign for the same alpha, the per-period annualisation is unreliable for that family;
  revisit with a new ADR.

## References

- `docs/spec/HELIOS_SRS_and_System_Design_v1.md`: §17.6 (horizon families), §19.3, §19.6, SIM-005, audit A-01
- `ARCHITECTURE_AND_TECH_STACK.md` §5.3 (horizon progression table)
- ADR-001 (horizon progression), ADR-002 (Fitness uses family-annualised Sharpe)
