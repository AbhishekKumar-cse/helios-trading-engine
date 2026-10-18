# NSE data and trading assumption validation

The audit is complete. The frozen source is **not ready for a validated historical Nifty research claim**. Membership, share units and session treatment require a new versioned dataset and protocol. Existing conditional research remains unchanged; G7 is not relaxed and TEST stays sealed.

Verified all 900 retained monthly response hashes and 50 Parquets containing 6,865,386 minute bars. The audit used 107 new public reference requests: 106 succeeded and one dated bhavcopy returned 404 on an exchange holiday. All 50 corporate-action requests succeeded. No credentials or new TEST prices were used.

## Historical membership

| Current symbol | Documented effective inclusion | Earlier retained minutes |
|---|---|---:|
| BSE | [2026-09-30](https://www.niftyindices.com/Press_Release/ind_prs10082026.pdf) | 137,310 |
| ETERNAL | [2025-03-28](https://www.niftyindices.com/Press_Release/ind_prs21022025.pdf) | 22,500 |
| INDIGO | [2025-09-30](https://www.niftyindices.com/Press_Release/ind_prs22082025.pdf) | 69,375 |
| JIOFIN | [2025-03-28](https://www.niftyindices.com/Press_Release/ind_prs21022025.pdf) | 22,500 |
| MAXHEALTH | [2025-09-30](https://www.niftyindices.com/Press_Release/ind_prs22082025.pdf) | 69,375 |

At least **321,060 source minutes** precede these documented inclusions. This is a count of raw source rows, not a count of model training samples or a proof that every other row has correct membership. The ZOMATO/ETERNAL alias was checked against actual official daily ISIN records.

Known historical members missing from the current-company snapshot include WIPRO, HEROMOTOCO, INDUSINDBK, BPCL and BRITANNIA. Temporary demerged constituents also require treatment. The four retained review notices are evidence of known changes; they do not establish a complete daily point-in-time membership history.

## Corporate actions and price units

The NSE returned 124 events: 110 dividend entries and 14 capital/other entries. Historical ISIN fields differ from the current roster in 53 event records. Ex-dates alone do not establish when a trading process knew an announcement; the audit does not backdate their availability.

44 dated exchange daily files gave 2,200 company/date comparisons. Of these, 100 have no retained minutes on the two excluded Budget dates, and 135 flag a large same-direction difference in both high and low prices. The other 1,965 have no large scale shift under the declared 5% screen; this is not full price, volume or executable-liquidity certification.

| Company | Sampled price-scale flags |
|---|---:|
| BAJFINANCE | 13 |
| BSE | 10 |
| HDFCBANK | 19 |
| KOTAKBANK | 33 |
| NESTLEIND | 17 |
| SHRIRAMFIN | 4 |
| TRENT | 39 |

For example, sampled BAJFINANCE highs/lows before its June 2025 capital action are about one tenth of the official contemporary daily prices. This is consistent with later split/bonus adjustment, an inference supported by the separate event records. Current share units cannot silently stand in for the historical whole shares used to allocate INR capital. Do not rescale on a ratio screen alone. Official closing-price benchmarks and last-minute closes also differ in definition.

## Market sessions

The reviewed calendar contains 366 normal weekday full sessions and two additional full Budget sessions across the source range. Their actual raw responses contain 18,750 candles per date across 50 companies; neither date survived the original weekday filter. Existing results explicitly used normal sessions, so their old coverage statement must retain that scope.

[2025 Budget session](https://nsearchives.nseindia.com/content/circulars/CMTR65729.pdf), [2026 Budget session](https://nsearchives.nseindia.com/content/circulars/CMTR72349.pdf). The retained TRAIN source also has 3,000 minutes from the one-hour [2025 Muhurat session](https://nsearchives.nseindia.com/content/circulars/CMTR70319.pdf). A new calendar must give this session its actual 13:45–14:45 window and 60 slots. It must not treat it as an ordinary 375-slot session.

## Explicit charge diagnostic

Added a Decimal charge estimator for same-day flat NSE cash-equity trades. It caps brokerage across partial fills of each order, applies buy-side stamp duty, daily security-VWAP STT with client-day rupee rounding, SEBI charges and GST. The exchange/IPFT components follow their dated circulars. The combined outflow is unchanged by the March 2026 reclassification; the components must not be double-counted.

The brokerage scenario uses the current public Zerodha tariff; it is not a verified historical account contract. Non-STT invoice rounding and contract-note reconciliation remain open. No delivery, overnight, auto-square-off, funding or real-money execution is claimed. Slippage remains an unverified 5-bps scenario.

| Retained minute formula | Old flat commission/tax INR | Reference charge estimate INR |
|---|---:|---:|
| momentum | 1,590,635.74 | 563,525.63 |
| reversal | 1,602,993.75 | 567,903.82 |
| volume_shock | 786,652.92 | 278,691.57 |
| trend_3 | 879,909.69 | 311,732.92 |
| reversal_3 | 883,984.88 | 313,177.84 |
| vol_scaled_trend | 763,911.78 | 270,639.15 |
| body_reversal | 934,453.55 | 331,053.97 |
| close_strength | 1,145,301.26 | 405,751.60 |
| close_fade | 994,652.23 | 352,382.40 |
| volume_trend | 1,431,457.80 | 507,133.60 |
| gap_reversal | 908,877.79 | 321,993.47 |

These are charge comparisons on the exact retained fills, not new backtests, model fits, candidate rankings or claims of profitable performance. Applying a different fee table to old quantities cannot fix membership, share-unit, liquidity or causal-outage assumptions.

Primary references: [NSE levies](https://www.nseindia.com/static/invest/first-time-investor-sebi-turnover-fees-stt-other-levies), [2024 exchange rates](https://nsearchives.nseindia.com/content/circulars/FA64232.pdf), [March 2026 reclassification](https://nsearchives.nseindia.com/content/circulars/FA73061.pdf), [public brokerage](https://zerodha.com/charges/), [NSE STT methodology](https://nsearchives.nseindia.com/content/circulars/cmtr5588.htm). Historical rates in the 2004 methodology circular are not used as current rates.

## Required rebuild before further performance research

1. Reconstruct effective-date membership and identity history, including missing and temporary constituents; collect only permitted TRAIN/VALID prices for that universe.
2. Establish historical raw share units, action factors and volume treatment against exchange evidence. Preserve adjusted prices separately and keep availability explicit.
3. Derive a new snapshot from retained raw bytes with versioned full and short sessions. Report missing observations; do not overwrite or fill the old snapshot.
4. Integrate an explicitly versioned, side/order/day-aware fee policy into new execution runs, with accepted billing/rounding rules and independent fill checks. Keep observed spread/impact and outage management as separate acceptance requirements.
5. Preregister a new research round after the source/protocol checks pass. Retrain on TRAIN only; retain failures and keep TEST sealed until authorized selection.

## Retained evidence

The compact companion JSON records counts, charge breakdowns, source hashes and archive location. The detailed audit, corporate events and daily comparisons remain local at `reports_out/nse_validation/20261018_reference1/assumption_audit.json` (SHA-256 `0b3d189b16551bda0b59c8c973aa5acbdb05a9eab51e779097711dcb41acd79d`). Raw references are in `reports_out/nse_validation/20261018_reference1` and `20261018_supplement1`. All 900 original monthly files and 50 source Parquets were checked read-only. Crypto fingerprints remain 25 definitions/34 results and TEST access is zero. No result, gate or source snapshot was overwritten.

After the audit, the comparison parser gained a fail-closed check for nonfinite official prices. All 2,100 observed-minute comparisons satisfy it; no measured value changed. The original audit runtime remains archived separately.
