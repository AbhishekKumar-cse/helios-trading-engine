# FI-2010 baselines

**Generated** by `scripts/fi2010_baselines_report.py` on 2026-09-20 from
`reports_out/`, written by `scripts/fi2010_baseline.py`.
Commit `8d4e23901c74` (uncommitted changes). Do not edit by hand: re-run the script instead.

Data: FI-2010 (Ntakaris et al., 2018), DeepLOB packaging. Trained on the first 80 % of days
1-7 (203,800 events), tested on days 8-10
(139,587 events). Inputs are the 40 order-book columns only.

## Results

| Model | Horizon | Seeds | Accuracy | Macro-F1 | Always "flat" | Fit time |
|---|---|---|---|---|---|---|
| `logistic_regression` | k = 10 | 3 | 0.7069 ± 0.0000 | **0.2814 ± 0.0000** | 0.7066 | 8.2 s |
| `mlp` | k = 10 | 3 | 0.7026 ± 0.0009 | **0.3441 ± 0.0101** | 0.7066 | 15.3 s |

Values are the mean ± standard deviation across seeds.

## Per seed

| Model | Horizon | Seed | Accuracy | Macro-F1 |
|---|---|---|---|---|
| `logistic_regression` | k = 10 | 0 | 0.7069 | 0.2814 |
| `logistic_regression` | k = 10 | 1 | 0.7069 | 0.2814 |
| `logistic_regression` | k = 10 | 2 | 0.7069 | 0.2814 |
| `mlp` | k = 10 | 0 | 0.7025 | 0.3551 |
| `mlp` | k = 10 | 1 | 0.7018 | 0.3351 |
| `mlp` | k = 10 | 2 | 0.7036 | 0.3420 |

## How to read this

- **Accuracy is misleading here.** About 60 % of the labels at k = 10 are "stationary", so
  always answering "flat" scores ~0.71 without learning anything. That number is in the
  table to compare against.
- **Macro-F1 is the measure that counts.** It scores the three classes (up, flat, down)
  equally, so a model that ignores two of them cannot win.
- **The spread across seeds matters.** A single lucky run proves nothing; a model whose
  macro-F1 swings widely between seeds has not really achieved its best number.
- Logistic regression is deterministic, so its seeds are expected to be identical: that is a
  check for hidden randomness, not a measure of variance.

## What this tells us

The best baseline so far is `mlp` with macro-F1
**0.3441 ± 0.0101** at k = 10.
Any later model — including the graph and transformer model planned for the 6th semester —
has to beat that number on the same split to be worth its complexity.

## Method notes

- The validation part is the **last** 20 % of the training file, in time order and never
  shuffled: shuffling would let a model train on events that happen after the ones it is
  validated on.
- The neural network runs a fixed number of passes with scikit-learn's early stopping
  switched off, because that feature would cut its own validation slice out of the training
  data by shuffling.
- Every run records its git commit, configuration fingerprint and seed.
