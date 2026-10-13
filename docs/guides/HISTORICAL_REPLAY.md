# Historical bar replay

`helios.data.replay.HistoricalBarSource` implements `MarketDataSource` in REPLAY
mode. Supply explicit date bounds, symbols, and the registered snapshot ID:

```python
from helios.data.replay import HistoricalBarSource

source = HistoricalBarSource(
    ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"),
    "2021-01-01", "2021-12-31",
    snapshot_id="9d75c8de86a8e981a9af61b17f76d1a7efc225f3d554366a152ba8f03968824f",
)
for bar in source.events():
    print(bar.close_time, bar.symbol)
```

The source checks the snapshot identity and selected partition checksums before
loading bars. It requires each instrument's observations to be chronological and
unique, then merges by exclusive recorded closing time and symbol. Inclusive
Binance closing timestamps retain their recorded precision: millisecond-normalized
values add 1,000 microseconds; microsecond values add one. Source timestamps are
preserved, including short and late intervals. `is_complete_interval` identifies
complete bars aligned to the expected interval.

`source.issues` exposes gaps and partial/off-grid observations as their events
become available. No observations are inserted, filled, or dropped. Set
`strict_gaps=True` to refuse the first affected event. Per-symbol sequence numbers
are replay ordinals; ingest time is the logical availability clock, not measured
exchange receipt latency. Consumers must respect issues and split authorization;
this source does not grant TEST access or execute orders. The trading event loop
and next-bar execution remain step 121.

## Actual verification, 2026-10-13

Replayed the complete 2021 hourly window from the above snapshot: **43,735 bars**,
8,747 each for BNBUSDT, BTCUSDT, ETHUSDT, SOLUSDT, and XRPUSDT. Every emitted
`(close_time, symbol)` key was nondecreasing. Observed 30 gap notices totaling 65
missing intervals and 19 partial/off-grid notices. One SOLUSDT recorded closing
timestamp extends beyond the nominal hour; replay preserves it and flags the bar.
The window lies in TRAIN; no TEST observations were loaded. Verification output
is retained locally at `reports_out/replay_verified.json`; bulk data stays out of Git.
