# Data quality report

**Generated** by `scripts/data_quality_report.py` on 2026-09-20 from
`data/processed/reports/`, written by `scripts/build_bars.py`.
Commit `6514355560d5` (uncommitted changes). Do not edit by hand: re-run the script instead.

Source: Binance public monthly klines (spot), every file checked against its published
SHA-256. **5,617,391 bars**, **609 missing bars** in total.

## Hourly (1h)

| Coin | Bars | First | Last | Bad rows | Off-grid | Gap runs | Missing | Longest gap |
|---|---|---|---|---|---|---|---|---|
| BTCUSDT | 79,117 | 2017-08-17 04:00 | 2026-08-31 23:00 | 0 | 43 | 28 | 170 | 2018-02-08 01:00:00+00:00 (75 bars) |
| ETHUSDT | 79,117 | 2017-08-17 04:00 | 2026-08-31 23:00 | 0 | 43 | 28 | 170 | 2018-02-08 01:00:00+00:00 (75 bars) |
| SOLUSDT | 53,063 | 2020-08-11 06:00 | 2026-08-31 23:00 | 0 | 0 | 10 | 19 | 2021-08-13 02:00:00+00:00 (4 bars) |
| BNBUSDT | 77,181 | 2017-11-06 03:00 | 2026-08-31 23:00 | 0 | 43 | 27 | 163 | 2018-02-08 01:00:00+00:00 (75 bars) |
| XRPUSDT | 72,913 | 2018-05-04 08:00 | 2026-08-31 23:00 | 0 | 0 | 25 | 87 | 2018-06-26 02:00:00+00:00 (10 bars) |

## Minute (1m)

| Coin | Bars | First | Last | Bad rows | Off-grid | Gap runs | Missing | Longest gap |
|---|---|---|---|---|---|---|---|---|
| BTCUSDT | 1,051,200 | 2024-09-01 00:00 | 2026-08-31 23:59 | 0 | 0 | 0 | 0 | - |
| ETHUSDT | 1,051,200 | 2024-09-01 00:00 | 2026-08-31 23:59 | 0 | 0 | 0 | 0 | - |
| SOLUSDT | 1,051,200 | 2024-09-01 00:00 | 2026-08-31 23:59 | 0 | 0 | 0 | 0 | - |
| BNBUSDT | 1,051,200 | 2024-09-01 00:00 | 2026-08-31 23:59 | 0 | 0 | 0 | 0 | - |
| XRPUSDT | 1,051,200 | 2024-09-01 00:00 | 2026-08-31 23:59 | 0 | 0 | 0 | 0 | - |

## What the columns mean

- **Bad rows** break a price or volume rule (step 047): a price at or below zero, a high
  below the open or close, a low above them, a negative volume or trade count, or a
  taker volume above the total. There are none in this data.
- **Off-grid** bars do not start exactly on the hour or minute. All of them are from
  **9-11 February 2018**, when Binance restarted after a long outage and the candles
  resumed at times like `09:28:14.789`. The files are not damaged; this is what the
  exchange published. These bars are kept, and listed in the validation reports.
- **Gap runs / missing** count bars the exchange never published, usually an outage or
  scheduled maintenance. **Gaps are never filled.** Inventing a price would put made-up
  data into every feature, backtest and result built on it.
- **Longest gap** is the start of the largest run, with its size in bars.

## Consequences for the research

1. The hourly history is usable: the worst coin is missing about 0.2 % of its bars.
2. Features must treat a gap as "unknown", never as "no change" (step 081 warm-up rule).
3. The February 2018 off-grid bars sit inside the hourly TRAIN period of ADR-004. Any
   feature that assumes a fixed hourly spacing must read timestamps, not row positions.
4. The minute data (2024-09 - 2026-08) has no gaps at all, so the minute horizon family
   needs no special handling.
