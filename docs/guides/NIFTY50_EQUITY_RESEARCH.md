# Nifty 50 equity research

The hourly alpha path now connects to the shared evaluator, backtest engine,
gates and registry. See [NSE shared research](NSE_SHARED_RESEARCH.md) for the
preregistered round, execution assumptions and coverage limitations. The daily/
hourly prediction pilot described below is retained as separate earlier evidence.

This extension downloads the current official Nifty 50 constituents and fits
separate daily/hourly LightGBM direction baselines. Crypto data, policies, fees,
registry results and existing execution are retained unchanged. See
[ADR-007](../decisions/ADR-007-equity-research-pilot.md) for scope and limitations.

Use the existing WSL Python environment, from the repository root:

```bash
/home/abhi/.venvs/helios/bin/python -m helios.data.equities
/home/abhi/.venvs/helios/bin/python -m helios.ml.equity_pilot data/equities/nifty50/SNAPSHOT_ID
/home/abhi/.venvs/helios/bin/python scripts/report_equity_pilot.py \
  reports_out/equities/RUN_ID --output docs/research/NEW_SUMMARY.json
/home/abhi/.venvs/helios/bin/python -m streamlit run dashboards/streamlit/app.py \
  --server.address 127.0.0.1 --server.port 8501 --server.headless true
```

Open [the equity lab](http://localhost:8501/?page=equities). It displays real equity
prices, source coverage, missing-minute counts, and retained model measurements.
Daily/hourly charts stop at VALID. No training button automatically reruns research.
If data has not downloaded, the page explains the missing prerequisite.

## What is downloaded

The constituent roster comes from the
[official Nifty Indices CSV](https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv).
All symbols are NSE EQ shares, identified by symbol, company and ISIN. BSE Ltd, if
present in the roster, is the company listed on NSE; this is not a BSE-venue feed.
The pilot uses [Yahoo's public finance API](https://ranaroussi.github.io/yfinance/)
for prices after the ordinary NSE history API returned HTTP 503 in preflight.
No access controls were bypassed and no keys, paid services or real orders are used.
Public Yahoo data has personal-use restrictions; arrange appropriate permissions
or a suitably licensed feed for shared/institutional use and redistribution.

Each collection creates a new directory in ignored `data/equities/nifty50/`:

- `constituents.csv`: exact official roster as fetched; it is **current membership**.
- `protocol.json`: frozen requested dates, splits, seed and model defaults.
- `raw/`: exact vendor response bytes, including corporate-action events.
- `bars/`: per-company, per-interval Parquet with raw vendor OHLCV, daily adjusted
  close, timestamps, conservative availability and full-bar flags.
- `manifest.json`: source URLs, fetch times, raw/processed hashes, company coverage,
  missing/nonfinite row counts, partial bars and explicit download failures.

Daily requests start in 2016; hourly requests start 2024-10-19. New listings and
vendor symbol changes can start later. Minute requests cover only the recent week.
Free intraday history is limited and can contain missing bars. Never interpolate
missing market observations or derive purported minute prices from larger bars.
Files are bulk local research inputs and must stay out of Git.

The fixed pilot cutoff is 2026-10-17 exclusive. A later collection needs a new
appropriately dated protocol, with split decisions made before reviewing results.
This is an on-demand collector; it is not a running continuous archive service.

## Model protocol

Both frequencies use ten causal, dimensionless features: returns, rolling
volatility, current body/range/close location, relative volume, opening gap and
intraday slot. Daily windows are 1/5/20 bars. The first hourly eligibility check
found systematic zero-volume opening bars; a 20-bar lookback left too little
usable history. Hourly windows are therefore 1/2/3 bars, frozen before fitting any
hourly model. Zero-volume bars remain excluded. This is an input-quality change,
not a choice based on hourly performance. Features are built separately for
each company. Daily return features use vendor adjusted closes; vendor historical
adjustments and ticker stitching have not been independently reconciled with NSE.
These are not point-in-time corporate-action data or historical membership data.

Predict the **next bar's open-to-close direction**. Daily labels use the next
observed session within seven calendar days. Hourly labels require consecutive
complete hours within the same session; overnight and missing-hour labels are
unavailable. Feature lookback resets after detected discontinuities. The normal
09:15–15:30 session contains six full hours plus a final fifteen-minute bar;
that partial hour is retained in data and excluded from the hourly model.
Special intraday sessions outside normal hours remain in raw responses and are
excluded, rather than silently mapped to the normal calendar. An independently
verified historical holiday/special-session calendar remains future work.

TRAIN/VALID boundaries and eight excluded calendar days are fixed in
`configs/equities/nifty50_pilot.yaml`. Labels crossing boundaries are purged.
TEST rows are filtered out by the Parquet reader before feature construction.
Downloading and hashing source files is ingestion/provenance work, not model TEST
evaluation. Charts likewise exclude reserved daily/hourly TEST observations.

One global model pools eligible companies for each frequency; companies need at
least 100 TRAIN and 20 VALID samples. Exclusions are explicit in the report.
LightGBM uses fixed seed, two threads and deterministic settings. VALID chooses
early stopping, making its scores development evidence. The comparison baseline
uses only the TRAIN direction prevalence. No parameter search or TEST metric is
calculated. Recent minute data is too short and incomplete for a defensible
long-history minute model, so no minute model is fitted.

Each fit creates an immutable ignored `reports_out/equities/RUN_ID/` containing
the protocol, feature protocol, source archives/hashes, dependency versions, model text files,
VALID predictions and `report.json`. It records dirty development lineage rather
than claiming the clean-tree reported-run standard. Nothing is written to the
alpha registry or promoted. Reports include pooled and per-company classification
metrics; these are not strategy returns or evidence of profitability.

## Next data requirements

For substantial minute history, add an authorized broker/data-provider historical
feed or supplied files with raw source provenance and corporate-action policy.
Do not assume the public endpoint can provide years of one-minute history.
Verify ISIN/rename/demerger history, historical constituents, calendar exceptions,
equity brokerage, exchange charges, taxes, settlement and slippage before adding
equity execution/backtest claims. Existing Binance fees and 365-day annualisation
must not be reused for NSE cash equities.
