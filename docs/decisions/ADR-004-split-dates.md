# ADR-004: Train / validation / test split dates

| | |
|---|---|
| **Status** | Accepted (2026-09-20, approved by team lead) |
| **Date** | 2026-09-20 |
| **Deciders** | Abhishek Kumar (team lead) |
| **Plan task** | 5A-12 (step 034) |
| **Replaces** | none |

## Context

Every alpha is judged on data it was not built on. If we tune an idea on the same period we
report, we measure luck, not skill. The spec requires (§20.6, BT-040 … BT-044, SIM-013):

- splits in **time order**, never random (market data is a time series);
- an **embargo** gap between splits at least as long as the prediction horizon, so a label
  (forward return) from one split never overlaps the next;
- the **TEST** split touched **at most twice** per alpha, every access logged (NFR-070).

The dates must be fixed **before** the first alpha is evaluated, otherwise they could be
chosen to make results look good.

Data on disk (checked 2026-09-20): BTCUSDT 1h klines from **2017-08-17 04:00** to
**2026-08-31 23:00** UTC; 1m klines from **2024-09-01 00:00** to **2026-08-31 23:59** UTC.

## Decision

All dates are **UTC calendar days, inclusive** (a split runs from 00:00 of its first day to
the last bar of its last day).

### H-HOURLY (embargo 7 days)

| Split | From | To | Days | Used for |
|---|---|---|---|---|
| TRAIN | 2018-01-01 | 2022-12-31 | 1,826 | Building features and fitting alpha weights / models |
| *embargo* | 2023-01-01 | 2023-01-07 | 7 | Not used for any metric |
| VALID | 2023-01-08 | 2024-06-30 | 540 | Choosing settings, comparing alphas, gate checks |
| *embargo* | 2024-07-01 | 2024-07-07 | 7 | Not used for any metric |
| TEST | 2024-07-08 | 2026-08-31 | 785 | Final confirmation only (max 2 accesses per alpha) |

### H-MINUTE (embargo 1 day)

| Split | From | To | Days | Used for |
|---|---|---|---|---|
| TRAIN | 2024-09-01 | 2025-08-31 | 365 | Building features and fitting |
| *embargo* | 2025-09-01 | 2025-09-01 | 1 | Not used for any metric |
| VALID | 2025-09-02 | 2026-02-28 | 180 | Choosing settings, comparing alphas, gate checks |
| *embargo* | 2026-03-01 | 2026-03-01 | 1 | Not used for any metric |
| TEST | 2026-03-02 | 2026-08-31 | 183 | Final confirmation only (max 2 accesses per alpha) |

### Rules

1. **Embargo ≥ horizon.** The embargo (7 days hourly, 1 day minute) must be at least as long
   as the longest label / forward-return horizon an alpha uses. An alpha with a longer
   horizon is refused, or needs a new ADR with a longer embargo.
2. **Features may look back, labels may not look forward across a boundary.** A feature at
   the start of VALID may use past bars from the embargo or TRAIN (that is information
   available at the time). A label whose forward window crosses a split boundary is dropped.
3. **Warm-up** bars at the start of each split are reported as UNAVAILABLE (step 081), not
   treated as zero.
4. **Coins listed later** (for example SOLUSDT, listed on Binance in 2020) only take part from
   their listing date (step 060); the dates above stay the same for every coin.
5. **Data before 2018-01-01** (Aug–Dec 2017) is not used for metrics: the first months after
   listing are thin and unrepresentative. It may serve as feature warm-up history.
6. The dates live in `configs/splits.yaml` (step 036) and every result records the config hash
   (step 027). **Changing a date needs a new ADR**, and all earlier results stay labelled with
   the old dates.

## Alternatives considered

| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| **A: fixed chronological splits with embargo (chosen)** | Simple, matches the spec, easy to audit | One fixed TEST window may be a lucky or unlucky regime | Walk-forward is added later for stability (G5), not instead |
| B: Random train/test split | More data mixing | Leaks the future into training | Forbidden for time series (BT-040) |
| C: Walk-forward only (rolling windows) | Tests many regimes | No untouched final hold-out; more complex | Planned as an extra (BT-042), TEST stays untouched |
| D: Plan's original dates (TEST from 2024-07-07, minute embargo inside the day) | Close to the draft | Uneven 6/7-day gaps | Harmonised to exactly 7-day and 1-day embargoes |

## Consequences

- **Good:** leakage-free, pre-committed evaluation windows; roughly 5 years of hourly
  training data covering several market regimes.
- **Bad / costs:** minute data only covers 2 years, so minute TRAIN is 1 year and TEST 6 months;
  about 14 hourly days and 2 minute days go unused as embargo.
- **Follow-up work:** `configs/splits.yaml` (step 036); split engine with embargo and TEST
  access counting (steps 067, 107); leakage tests (step 111).
- **How we will know it was wrong:** if VALID and TEST results diverge systematically across
  many alphas, the split may sit on a regime change; revisit with walk-forward evaluation.

## References

- `docs/spec/HELIOS_SRS_and_System_Design_v1.md`: §20.5–§20.6, BT-021 … BT-044, NFR-070, SIM-013
- `5thSem/5thSem_Plan.md`: suggested split table (5A-12)
- ADR-003 (horizon families)
