# Historical NSE minute rebuild

ADR010 adds an opt-in conditional cohort; it leaves every v1 snapshot and result
intact. The original assumption audit remains a record of the original data.

The reconstruction starts from the retained current roster and reverses the
official March2025, September2025 and September2026 Nifty reviews. It records
temporary ITCHOTELS, TMCV and KWIL membership, including non-tradable dummy periods.
Official listing-day files identify their initial BE series; BE is never silently
accepted as EQ. This is retrospective membership evidence, not a feed captured
at each historical decision time. BSE stock is outside this study window's Nifty
membership; this project still does not ingest BSE-exchange trading data.

The separate snapshot retains provider OHLCV unchanged. Known capital-action
histories, identity failures, daily scale mismatches, gaps and zero-volume days
are excluded from its research cohort. No ratio is used to invent raw historical
prices or share quantities. Every available scheduled day has an official daily
reference; passing the fixed 0.2% extreme-price screen is explicitly weaker than
minute-price/volume certification. Surviving data remains conditional on ex-post
completeness. Calendar coverage includes both full Budget weekend sessions and
the October2025 60-minute Muhurat session.

Reproduce using the documented WSL environment, with new exclusive output IDs:

```bash
python scripts/collect_nse_rebuild.py ORIGINAL ORIGINAL_REFERENCES NEW_REFERENCES
python scripts/collect_nse_historical_members.py \
  NEW_REFERENCES/historical_identities.json NEW_MEMBER_HISTORY
python scripts/build_nse_repaired_snapshot.py \
  ORIGINAL ORIGINAL_REFERENCES NEW_REFERENCES NEW_MEMBER_HISTORY NEW_SNAPSHOT
python scripts/freeze_equity_round.py NEW_SNAPSHOT \
  --round-id nse_new_repaired_id --interval 1m --repaired \
  --suite baseline --research-symbols RELIANCE --workers 2
```

Public refusals remain evidence; collectors do not bypass authentication. TEST
prices are outside every collection range. Bulk files/models stay outside Git.
Collector/builder copies and response hashes retain development lineage.

The versioned execution charges reserve commission/statutory fees causally per
backtest fill. PAPER retains its separately accepted policy until market-hours
acceptance and settlement handling are validated. In the v2 backtest, fees accrue per
fill, including order-level brokerage caps and sell-notional provisional STT.
At the flat session end, a signed fee adjustment settles to the independent
security/day VWAP STT estimator and client/day rounding. The adjustment changes
cash/fees, never the fill log, shares or realized gross trading P&L. Stored
evidence includes both fills and settlement records. The 2x replay multiplies
charges and slippage. Current public brokerage remains a scenario; historical
contract-note reconciliation and observed liquidity/slippage are unresolved.

The model uses fixed TRAIN-only fit/calibration dates and parameters from ADR009,
with a fixed approximate 21-bps entry hurdle for v2. Accepted sessions from
historical members supply fit data; excluded prices cannot silently re-enter
through the old loader. Shared VALID evaluation, gates and immutable registry
writes remain in use. The dashboard exposes the rebuilt cohort separately from
original experiments and shows quarantines, training counts and actual fills.

G7 remains closed. A completed source rebuild or a finished negative research
round is not a profitable alpha, certified data feed, operational PAPER trial,
or fifth-semester exit. Those require their own measured evidence.
