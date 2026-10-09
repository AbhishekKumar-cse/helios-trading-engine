# DeepLOB TRAIN smoke run (step 087)

From the repository root in the documented WSL Python environment:

```bash
uv run python scripts/fi2010_deeplob.py
```

Defaults: CPU, seed 0, one epoch, the first 1,024 chronological windows, batch 32,
Adam learning rate 0.001 and two PyTorch threads. `--zip`, `--out-dir`, `--seed`,
`--epochs`, `--max-windows`, `--batch-size` and `--device` override the exposed run
choices. The library's `DeepLOBTrainingConfig` additionally exposes the supported
FI-2010 label horizons and validation fraction. The existing full-size DeepLOB
architecture is used; it is not replaced by a smaller model for the smoke test.

This is **one epoch over a bounded TRAIN subset**, not an epoch over the whole
203,800-event training period. It tests the training path on real data without
claiming benchmark accuracy. Full training/evaluation over three seeds is step 099.
No validation/test score or baseline comparison is produced in step 087.

`load_training_windows` reads only the days 1–7 training member from the existing
archive. Its first 80% is TRAIN and its last 20% remains reserved for validation,
as in the existing loader. Test days 8–10 are never parsed. The archive itself is
hashed for source identity, including its compressed bytes, without evaluating
held-out observations. The packaged file supplies event order, not day/stock
boundary metadata; no new boundaries or observations are invented.

Each input contains 100 consecutive order-book events, ending at t, with the label
at t. Labels 1/2/3 (up/flat/down) become cross-entropy indices 0/1/2. The last k
possible endpoints are removed so their forward labels cannot cross the TRAIN
cutoff. Windows stay inside TRAIN and are not shuffled. Per-column mean/std is
fitted only to the selected training input events; constant columns use scale 1.
This is a fitted training transform, not an online/rolling feature calculation.
Overlapping windows share stored events rather than duplicating large arrays.

The model uses train mode during optimization. Loss before and after the epoch is
measured on the **same training windows in eval mode**, including BatchNorm, using
sample-weighted cross-entropy. The online training-mode epoch loss is stored
separately and must not be compared directly to either eval-mode loss. All batches,
including a short final batch, are trained. Non-finite losses/gradients fail explicitly.

Python/numpy/PyTorch seeds are fixed through the common helper; deterministic
PyTorch algorithms are required and no retries select a seed with better loss.
Thread/determinism settings are restored for callers. CUDA requires an explicitly
requested available GPU and compatible PyTorch installation (the documented local
install is CPU-only); unavailable devices or nondeterministic operations fail
rather than silently changing device or relaxing determinism. Determinism is
checked in the same environment, not promised across different hardware/releases.

Every CLI invocation writes a fresh run directory under ignored `reports_out/deeplob/`:

- `smoke.json`: config, commit/dirty flag, config hash, archive SHA-256, seed,
  UTC time, selected source/label bounds, actual losses, elapsed training time,
  PyTorch version and checkpoint hash.
- `model.pt`: model state and the fitted input mean/std with config. This is an
  inference checkpoint, not a resumable optimizer checkpoint.

Existing run directories are never overwritten. The command exits 0 when the
measured final TRAIN loss is lower, or 1 when it is not; either outcome is recorded
without inventing or retrying a successful result. Outputs and checkpoints stay
out of Git. A dirty run is explicitly a development diagnostic; reported benchmark
results later require committed code and their full evaluation lineage.

The actual 2026-10-09 CPU smoke run used seed 0, horizon 10 and 1,024 windows
(1,123 input events, 32 optimizer steps). Source events: 254,750; exclusive TRAIN
cutoff: 203,800; last window endpoint: 1,122; last forward-label endpoint: 1,132.
TRAIN eval cross-entropy fell from **1.0921491794 to 1.0267122071**. Training took
18.32 seconds, excluding archive loading. Its development lineage records
`d278ee3fcb99ccdf65e51ab2fd79632360614720`, `dirty=true`, PyTorch `2.14.0+cpu`.
The measured record is
`reports_out/deeplob/20261009T053345Z-fdb3e290fc2f/smoke.json`. This loss decrease
shows the optimizer path works; it is not evidence of held-out predictive quality.
