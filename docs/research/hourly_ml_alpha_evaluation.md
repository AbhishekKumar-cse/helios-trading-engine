# Frozen hourly ML alpha: VALID evaluation

On 2026-10-15, experiment **5146** completed the five fixed VALID evaluations of
`hourly_ml_v1`, version 1, provenance **ML**. It was preregistered from clean
`5fa72f20a0bdbd1a773db7bc7b0e109acb7aa569` before adapter implementation or
evaluation. All five results ran from clean implementation commit
`ba6ead5720572dc123143b056598fc707d5e7bb1`, with seed 0, 168 warm-up rows,
accepted costs/splits/G1–G6 and the original data snapshot.

| Symbol | Result | Run ID |
|---|---|---|
| BNBUSDT | INVALID | 690ce5bb-7e33-40ee-a530-52da0e4edafc |
| BTCUSDT | INVALID | add8a54f-9b6a-49a2-872c-1d641c447fc1 |
| ETHUSDT | INVALID | bc905650-40b3-45c3-9db8-ef6c8d35ef71 |
| SOLUSDT | INVALID | 708fbbcf-74cb-46b0-8e1d-6f58dfce52b0 |
| XRPUSDT | INVALID | a067c011-e0b3-46d0-86a0-fb43a67d0c12 |

Every attempt records **UNAVAILABLE_AFTER_WARMUP** and **DATA_GAPS**. Sharpe,
Fitness and other performance metrics remain NULL. The common gate evaluator
retains all six failed gate outcomes with unavailable measurement evidence.
This establishes an invalid research measurement, not losing profitability or
an independent TEST result. No candidate is promoted.

The original step-137 transform has 63,945 typed AlphaValues, all UNAVAILABLE
because calibration fitted the complete VALID period and becomes available only
after it ends. Retrospective normalized diagnostics were not substituted for
actionable signals. Prior TRAIN/VALID fitting, early stopping, calibration and
diagnostic exposure was declared in preregistration. The existing classifier,
calibration and TRAIN payoff policy were not refitted or tuned.

The immutable registered model reference anchors the complete transform report:
`sha256:b33db60889703d71024602b530d29c44f7d25f6467c150bb65cdb1e5b7ed5803`.
The adapter verifies all linked artifacts and reproduces the frozen transform,
then passes typed values through the same split validity, simulator, costs,
metrics and gate/result implementation as expression alphas. Synthetic tests
separately exercise the valid post-calibration metric path and guarded TEST
reservation; those are fixtures, not market observations.

The local outcome manifest is
`reports_out/hourly_ml_evaluation/experiment-5146.json`, SHA-256
`4f148ce8cc2a3bd67562deefc6a84140b201dbd8102c5177387d7c06cfabfebf`.
It identifies each immutable evaluation artifact and its verified digest.
`reports_out/steps_141_145_verified.json` verifies the five database rows, clean
source, experiment chronology and artifact hashes. It also confirms that the
original 17 quantitative result rows and 11 definitions retain their prior
hashes, and all 12 research alpha TEST counters remain zero.

There are now 22 retained simulator attempts: 17 prior quantitative attempts and
five ML instrument evaluations, across 12 fixed definitions. All are INVALID;
there is no valid best score or profitability comparison. Model training,
calibration and transformation experiments remain distinct from these five
simulator attempts. A future usable ML evaluation requires a separately
preregistered post-calibration inference artifact and guarded data access.

Reproduction and operational entry point:
[registered ML alpha guide](../guides/REGISTERED_ML_ALPHA.md).
The completed experiment must not be silently rerun; retain its manifest/rows.
