# Minute feature export (152)

On 2026-10-15 the unchanged feature exporter ran from clean source
`75022f44eb26dd4f78a7aa2372504d840637e07d`:

```bash
/home/abhi/.venvs/helios/bin/python scripts/build_features.py --interval 1m
```

All configured coins completed: BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT and XRPUSDT.
Each has **1,051,200 rows**, **21 features**, 21 boolean availability columns and
three UTC-year Parquet partitions (2024–2026). The total is **5,256,000 rows** in
15 partitions. The interval argument is the only implementation change between
the prior hourly build and this minute build; no feature or exporter code changed.
Lookbacks count bars, so a 24-bar feature now spans 24 minutes.

Observed coverage is 2024-09-01 00:00 through 2026-08-31 23:59 UTC, with exact
one-minute timestamp spacing and zero off-grid rows for every coin. Source and
output file checksums were verified. Every unavailable feature remains NaN with
a false mask; every available value is finite, and declared warm-up rows remain
unavailable. Computation across year boundaries preserves trailing history.
The existing feature-store suite passed all 14 tests, including minute export,
year boundaries and gaps.

The [verification inventory](minute_feature_build.json) records per-coin input
snapshot IDs, source/config lineage, manifest hashes and all 15 output hashes.
Bulk outputs remain ignored under
`data/processed/features/feature_set=v1/interval=1m/`; they are not committed.
The original 51 hourly feature/manifest files retain their checksums. The 22
research results and 12 definitions remain unchanged; TEST-access counts are zero.

This is label-free preprocessing of the stored history, including dates assigned
to later splits. It does not fit a model, inspect TEST performance, select an
alpha or authorize TEST evaluation. Consumers must enforce the accepted split,
embargo and availability rules before research measurements. No minute alpha
performance or successful gate outcome is claimed.

Build log and independent verification remain locally in
`reports_out/step152_build.log` and `reports_out/step152_features_verified.json`.
See [feature-store behavior](../guides/FEATURE_STORE.md) for the existing schema
and CLI.
