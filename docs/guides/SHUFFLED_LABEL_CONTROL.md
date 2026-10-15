# Shuffled-label ML control (146)

`research/tests/test_shuffled_labels.py` is marked `leakage` and runs in the
required CI job. It uses the existing fixed logistic and LightGBM training
functions, including TRAIN-only scaling and VALID early stopping where applicable.
It creates independent synthetic chronological TRAIN/VALID windows with 2,048
usable samples each and a planted feature-to-next-return relationship. Both
unshuffled positive controls must exceed 0.97 accuracy and 0.99 AUROC.

Ten fixed permutation seeds (0–9) independently shuffle targets within each
split. Features, timestamps, label windows, class counts and original datasets
remain unchanged. The mean shuffled accuracy and AUROC for each classifier
must lie within 0.05 of chance (0.5); this bound was fixed before execution.
There is no seed selection, model tuning or shuffle across split boundaries.

Observed synthetic control means on 2026-10-15:

| Classifier | Accuracy | AUROC |
|---|---:|---:|
| Logistic | 0.49121094 | 0.50544501 |
| LightGBM | 0.48242188 | 0.49994670 |

Both positive controls and both shuffled controls passed. These are CI fixture
diagnostics, not market measurements, new research fits, or trading performance.
No real saved classifier/calibration is refitted and no TEST data is loaded.

```bash
/home/abhi/.venvs/helios/bin/pytest -q -m leakage --strict-markers
```
