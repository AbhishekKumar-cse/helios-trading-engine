# Fixed hourly ML baselines (125)

`scripts/train_hourly_baselines.py --experiment-id 4369` runs the fixed preregistered
protocol in `helios.ml.hourly_baselines`. Experiment 4369 was registered on
2026-10-14 from clean source `6b60e28` before fitting or inspecting metrics.
It uses the existing all-five-coin hourly snapshot
`9d75c8de86a8e981a9af61b17f76d1a7efc225f3d554366a152ba8f03968824f`.

The eight features are log returns over 1/4/24 hours, volatility over 24 hours,
volume z-score over 168 hours, taker-buy ratio, and hour-of-day sine/cosine. Target
is the one-hour forward close return; logistic direction is positive return vs
nonpositive return. Ridge alpha and logistic C are both 1, seed 0, tolerance 1e-6,
and maximum iterations 1,000. Ridge uses LSQR and logistic uses LBFGS. No validation
tuning, class balancing, probability calibration, threshold search or TEST scoring
occurs. The accepted TRAIN/VALID split and embargo remain unchanged.

Both pipelines fit StandardScaler exclusively on TRAIN. Observations must have
complete on-grid bars and paired available features with contiguous forward
labels. Off-grid/incomplete bars, unavailable features and labels are explicitly
counted and excluded, never filled. Boundary-crossing labels are purged. This is
a supervised prediction sample policy; it does not repair the INVALID alpha
simulations from step 119 or make a trading P&L series complete.

Actual input verification yielded **174,959 TRAIN** and **63,945 VALID** samples.
TRAIN has 129 off-grid bars and 46 incomplete on-grid bars excluded; VALID has five
incomplete on-grid bars excluded. Availability counts and source exclusions are
stored separately per split and coin. Feature manifests, their selected files
and the corresponding bar partitions are hash-verified before observations load.
Original feature-build lineage and sample/input hashes remain in the result.

The entry point refuses a dirty source before loading observations, and requires
an open ML experiment declaring this exact protocol. Consequently the verified
implementation is committed before the actual measurement run; its metric/model
artifacts are generated from that clean commit before the final collective push.
The run writes a fresh UUID directory under `reports_out/hourly_linear/` containing
metrics.json, both model checkpoints and VALID predictions, with artifact hashes.
It never overwrites or selects a best run. Generated artifacts stay outside Git.

Metrics include ridge RMSE, MAE and R², compared with the TRAIN-mean return
baseline; logistic accuracy, macro-F1, log loss and AUROC, compared with the
TRAIN-majority class. Undefined R²/AUROC stay null. Convergence status is recorded.
These are predictive VALID metrics, not net trading returns or gate approval.
Later steps cover LightGBM, calibration and model-to-alpha integration.
