# Frozen ML alpha evaluation (step 145)

`helios.ml.registered_alpha` adapts the step-137 frozen typed signals into the
same `helios.sim.evaluate.evaluate` entry point used by expression alphas.
The immutable definition has provenance ML, a SHA-256 reference to the complete
transform report, the classifier hash, policy hash and original transform commit.
The report transitively anchors the classifier, saved probabilities, calibration,
TRAIN payoff policy and typed AlphaValue artifacts. Every load verifies these
hashes and reproduces the transform without refitting any model.

The adapter maps a typed close decision timestamp back one hour to its originating
bar. The existing lag-one simulator then handles execution/returns as before.
Unavailable values stay unavailable; retrospective diagnostic scores never become
signals. Absent ML rows align as unavailable against the complete observed bars.
Invalidity, accepted costs, metrics, Fitness, stability, cost sensitivity, IC,
G1–G6 and immutable result storage share the expression evaluation implementation.
TEST reservation still commits before either market inputs or ML artifacts load.
TRAIN evaluation refuses this VALID-calibrated artifact before reading its files,
so a historical TRAIN request cannot inspect future VALID predictions.

For the existing run, calibration fitted the complete VALID window. Its fitted
map becomes available only after VALID ends, so all 63,945 saved typed values
are unavailable for those historical decisions. Their predictive diagnostics do
not establish tradable VALID performance. These evaluations must retain INVALID
evidence and NULL performance metrics. No new TEST data, refits, gate changes or
promotion are part of this step. A future post-calibration inference artifact
requires its own preregistration and guarded data access.

The five fixed VALID attempts were preregistered as experiment **5146** from clean
step-144 source before implementing the adapter. Prior TRAIN/VALID model selection
and diagnostics exposure is declared. Use the documented WSL environment:

```bash
/home/abhi/.venvs/helios/bin/python scripts/evaluate_ml_alpha.py \
  --metrics reports_out/hourly_ml_alpha/49f79810-f5fe-4704-878d-117c2e973de4/metrics.json \
  --experiment-id 5146
```

The command requires clean source and an exact PLANNED preregistration, registers
the definition, and evaluates BNB/BTC/ETH/SOL/XRP once each on VALID. The common
evaluator captures the clean implementation commit in every result. It writes
`reports_out/hourly_ml_evaluation/experiment-5146.json` with individual immutable
result/artifact references, and marks the experiment FINISHED after all five.
Existing manifests/results and RUNNING/FINISHED experiments prevent automatic
reruns. Partial failures retain completed rows and progress for explicit recovery.

Experiment 5146 is now FINISHED. All five actual rows are INVALID, with NULL
performance metrics and zero TEST accesses. Verified results and lineage:
[frozen hourly ML evaluation](../research/hourly_ml_alpha_evaluation.md).

Tests use synthetic linked artifacts and rolled-back PostgreSQL rows. They cover
hash tampering, causal unavailable VALID signals and a post-calibration synthetic
TEST case that reaches metrics and all six gates. That case remains REJECTED
when gates fail, and consumes exactly one rolled-back TEST reservation. Synthetic
fixtures are not market observations or measured research performance.
