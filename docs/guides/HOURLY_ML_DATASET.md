# Hourly ML dataset

## Feature and target alignment (114)

`DatasetConfig(features=(...), horizon=h)` declares an ordered, nonempty unique
feature list, hourly interval and feature-set version. `load_feature_frame` reads
those values and their `available__...` columns from the existing Parquet feature
store over explicit UTC bounds. It is a low-level reader, not TEST authorization.

`build_dataset(features_by_symbol, bars_by_symbol, config=..., snapshot_id=...)`
aligns each feature at timestamp t with `close[t+h]/close[t]-1`, using actual
consecutive hourly intervals. It requires every selected feature available and
finite, plus finite positive endpoint prices and a complete label window. Missing
intervals never produce a shorter effective horizon. Warm-up, absent feature rows,
unknown prices and final h rows are unavailable; excluded counts are recorded.
Feature and label exclusion counts can overlap. Claimed available non-finite
features, malformed timestamps/types/masks and non-positive finite prices fail.

The builder accepts causal FeatureFrame outputs; it cannot prove causality of
arbitrary caller-created features. It fits no scaler, centers no full-sample data,
shuffles no rows and chooses no model. Scaling belongs to the later TRAIN-only
model pipeline. Continuous forward-return targets support regression; later
classification must declare its own label convention.

Samples are immutable tuples ordered by (timestamp, symbol). X/y properties
materialize independent NumPy arrays, with correct empty shapes when no pair is
usable. Exact feature/price/timestamp/mask hashes, config JSON/hash, per-symbol
counts and optional caller-supplied snapshot ID are retained. Snapshot IDs are not
invented or independently verified by this pure builder. No results are persisted,
and no TEST dataset was used in implementation verification.
