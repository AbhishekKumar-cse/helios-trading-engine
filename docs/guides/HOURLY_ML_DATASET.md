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

## Purging, embargo and guarded loading (115)

`dataset_for_split(dataset, window)` excludes samples outside the accepted split
dates (including embargo rows) and drops every label whose endpoint is at or
beyond the split's exclusive end. It verifies the exact split configuration,
hourly horizon and each sample's label-window length. Original source hashes and
availability counts remain intact; separate outside/purged counts explain the
partition. X remains features at the decision bar; no future price enters X.
open_time/label_end_time identify bars, whose close prices define the target;
features are available after their decision bar closes, not at its opening.

`build_split_dataset(engine, ..., load_inputs=callback)` resolves the accepted
window from splits.yaml, checks embargo >= horizon and the registered alpha's
family/horizon, and loads only one requested split. Earlier causal feature history
is allowed, but future feature/price rows beyond the authorized end are refused.
Without later rows the final h labels are unavailable, so boundary exclusion does
not require inspecting the next split or its embargo. The pure partition helper
can also purge crossing labels in already-authorized prepared data; it cannot
retroactively authorize earlier inspection.

TEST requires the step-067 reservation, matching alpha/version and experiment
snapshot. That reservation commits before the trusted callback runs; a failed load
still consumes access, and the third attempt is refused before loading. The
returned access must be reused by later persistence, not counted a second time.
TRAIN/VALID consume no TEST access. No model, scaler or result is fitted/stored.
Caller loading/feature causality remain explicit responsibilities.

Tests use synthetic data and rolled-back PostgreSQL fixtures. Exact-boundary
purging, embargo exclusion and future perturbation are marked leakage and run
in the required CI job. No real TEST observations were read for verification.
