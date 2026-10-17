# ADR-007: Add Nifty 50 equity research

Status: Accepted scope, 2026-10-17, explicitly requested by the user. Pilot defaults
below are experimental configuration, not a change to accepted crypto policies.

Add Indian cash-equity research alongside the existing crypto framework. Freeze
the official Nifty Indices constituent CSV at collection time, including company,
symbol and ISIN. Historical prices for these current constituents are a
survivorship-biased current-universe study, not a historical Nifty index backtest.
Historical membership and symbol/ISIN changes need separate point-in-time data.

The ordinary NSE history API returned HTTP 503 during source preflight. Use
Yahoo-distributed NSE-listed prices for the local research pilot, recording exact
requests, raw bytes, adjustments, timestamps, exclusions and hashes. These are not
official NSE price files. No redistribution rights or production data quality are
assumed. Public Yahoo data is intended for personal research; institutional/shared
use needs a source with suitable permissions.

Daily history starts in 2016 where available; hourly history starts 2024-10-19;
minute history starts 2026-10-10. Download through 2026-10-16, exclusive of the next
day. Free intraday coverage is limited: never manufacture older minute bars from
hourly/daily data. Capture recent minutes now for ingestion checks, not model claims.

Use a separate equity adapter for INR, Asia/Kolkata and exchange sessions. Normal
cash sessions run 09:15–15:30. Retain vendor partial bars with an explicit flag;
exclude partial hourly bars and non-normal intraday sessions from model inputs.
No weekend filling, zero filling or synthetic market observations. Daily bars use
conservative next-midnight availability. Preserve vendor corporate actions and
adjusted closes; full-snapshot adjustments are not point-in-time fundamentals.

Freeze configs/equities/nifty50_pilot.yaml before fitting. Daily TRAIN ends 2022,
VALID runs 2023-01-09 through 2024; TEST starts 2025-01-09. Hourly TRAIN ends 2025,
VALID runs 2026-01-09 through June; TEST starts 2026-07-09. Each boundary has eight
excluded calendar days. Never read TEST bars into features or labels for this pilot.
Purging and availability checks also apply to next-bar labels.

Fit one fixed deterministic LightGBM direction baseline per daily/hourly frequency,
compared with a TRAIN-only constant-probability baseline. VALID selects early
stopping, so it is development evidence, not an untouched final test. Predict the
next observed bar's open-to-close direction; hourly targets must be consecutive
full bars within the same session. No parameter search, profitability claim,
registry promotion, TEST evaluation or equity execution is authorized by this fit.

Development runs may record dirty=true plus exact source hashes, with no claim to
the existing clean-tree reported-run standard. Existing crypto ADRs, split dates,
fees, registry results and simulator remain unchanged. Equity brokerage, taxes,
slippage, corporate-action verification and official calendar validation must be
implemented before tradable backtest/paper claims.

Sources: [official constituents](https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv),
[NSE sessions](https://www.nseindia.com/static/market-data/market-timings),
[Yahoo API research client documentation](https://ranaroussi.github.io/yfinance/).
