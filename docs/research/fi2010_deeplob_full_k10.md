# FI-2010 DeepLOB full TRAIN run, k=10

Status: complete, recovered and verified locally on 2026-10-12. All three reports
and checkpoints are retained outside Git. These are development VALID results, not a clean
published benchmark reproduction or evidence of trading profitability.

The recovery protocol was written before training on 2026-10-11 at 19:54:26 UTC. It fixes
seeds 0/1/2, five epochs, Adam learning rate 0.001, batch size 128, chronological
batches and deterministic algorithms. Every eligible TRAIN window is used; no seed
is selected or retried on the basis of its score. All three use the final epoch.

The days 1–7 member contains 254,750 events. The chronological 80% cutoff is
203,800; endpoint purging leaves 203,691 TRAIN and 50,841 VALID windows. VALID
normalization uses TRAIN statistics. Days 8–10 TEST members are not parsed.
The packaged data lacks sufficient stock/day boundary metadata to claim that no
window crosses those boundaries. See [training guide](../guides/DEEPLOB_TRAINING.md).

| Seed | VALID accuracy | VALID macro-F1 | Optimizer steps | Fit seconds |
|---|---:|---:|---:|---:|
| 0 | 0.7271690171 | 0.5857987773 | 7,960 | 1,083.07 |
| 1 | 0.6961704136 | 0.5078407930 | 7,960 | 1,076.89 |
| 2 | 0.7241596349 | 0.5842850009 | 7,960 | 1,077.83 |

Accuracy and macro-F1 are independently recalculable from each saved confusion
matrix. Macro-F1 includes all three classes, with undefined class F1 set to zero.
All three seeds were independently checked locally against their recorded scores,
and all checkpoints loaded strictly into the model on CPU. Source, archive,
protocol and checkpoint hashes, configs, split bounds and window counts matched.

Confusion matrices use true classes as rows and predicted classes as columns,
in up / flat / down order (original labels 1 / 2 / 3):

```text
seed 0: [[3306, 5045,  926],
         [ 964,30190, 1067],
         [1057, 4812, 3474]]
seed 1: [[2291, 6259,  727],
         [ 766,30747,  708],
         [ 770, 6217, 2356]]
seed 2: [[3306, 4901, 1070],
         [1116,29980, 1125],
         [ 968, 4844, 3531]]
```

Checkpoint SHA-256:

- Seed 0: `ede9269c4d2522df343b0f198fc229076e2b2ad85a48f5f992215e4444dec11f`
- Seed 1: `19e410ac592d3547e506a99bc4612d8309575f120d6ba7dcf3c946b76146cdb9`
- Seed 2: `14bd5be7cc6d14518f6b83e33a7cceb74cf309757a87fa9b5ba507a238afac73`

Runtime: free Colab Tesla T4, Python 3.13.15, PyTorch 2.11.0+cu130. This differs
from the local CPU environment; these are actual recorded runtime versions.
The source manifest identifies `781dc1b4dbd4955e4875da5a646900b32170af6e`,
`dirty=true`, and hashes every exported source file. The new runner/evaluator were
uncommitted when exported; that dirty lineage is retained without relabelling it.

Recovery evidence directory: `reports_out/deeplob_full/20261011T195426Z-fd1b60d1cd91/`.
Reports and checkpoints remain outside Git. The raw protocol SHA-256 is
`d6e9b8b57ce3484a7193628e9732ad0ffd61671702ca3365ba23ee8b6c3b97dd`.
The archive SHA-256 is
`7a5564290a504bdc104dccaf44aa6c0b3857bf1db6b0517b9b88577c2def3e5f`.

The browser upload truncated the dataset; the runner refused its checksum.
The [author's public archive](https://github.com/zcakhaa/DeepLOB-Deep-Convolutional-Neural-Networks-for-Limit-Order-Books/blob/master/data/data.zip)
was downloaded inside Colab and matched the exact local checksum (56,278,154 bytes).
During training, the notebook stayed on Connecting and reported misleading runtime
errors. The terminal confirmed that the original training process survived; seed
0 subsequently saved its checkpoint and report. The saved notebook later recorded
successful completion, but the temporary runtime expired before seeds 1/2 could be
backed up locally. Their original scores are therefore not reported. The complete
fixed protocol was repeated to recover evidence, using the same verified source,
data and runtime versions, without changing settings or selecting a better score.
Original seed 0 remains under `reports_out/deeplob_full/20261010T200755Z-6ee387334764/`
(fit 1,034.56 seconds). Recovery seed 0 has the identical full confusion matrix,
scores and checkpoint SHA-256:
`ede9269c4d2522df343b0f198fc229076e2b2ad85a48f5f992215e4444dec11f`.
Its raw protocol differs because it records the new run time. The original protocol
SHA-256 remains `66577759a2715c9112355260e7209b69166663f53f81e3cc53fec17aeefa1d70`.
