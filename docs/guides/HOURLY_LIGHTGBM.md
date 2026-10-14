# Fixed LightGBM hourly baseline (126)

The direction model uses the same eight features, five coins, paired-observation
policy and accepted TRAIN/VALID splits as the fixed linear baselines. Seed 0,
500 maximum trees, learning rate 0.05, 31 leaves, 100 minimum child observations,
L2 regularization 1 and 50 stopping rounds are fixed before fitting. CPU training
uses two threads, deterministic mode and column-wise histograms. No scaling,
class-weight search, probability calibration or TEST access occurs.

The official [early-stopping callback](https://lightgbm.readthedocs.io/en/latest/pythonapi/lightgbm.early_stopping.html)
selects the best iteration using VALID binary log loss. Consequently VALID scores
are development scores affected by this selection, not an independent test.
Earlier linear VALID measurements are known; this is not a claim of blind VALID
research. Scores, best iteration, source/sample hashes and original feature-build
lineage are retained, including weak outcomes.

Preregister the exact `lightgbm_protocol(LightGBMConfig())` as an ML experiment,
then invoke `scripts/train_hourly_lightgbm.py --experiment-id ID` from clean Git.
This writes an immutable UUID directory under `reports_out/hourly_lightgbm` with
metrics, model checkpoint and VALID predictions plus artifact hashes. Native
LightGBM 4.7.0 and its dependencies are locked in uv.lock. Prediction metrics do
not establish profitable simulated execution or approval by alpha gates.
