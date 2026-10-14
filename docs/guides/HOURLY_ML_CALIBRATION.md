# Hourly calibration and ML alpha (136 onward)

Step 136 fits one increasing isotonic map on the existing LightGBM VALID
predictions. It verifies the source checkpoint and prediction hashes, split
bounds, chronological symbol/time identity and labels before fitting. No model
retraining, parameter search or TEST reading occurs. The exact source hash and
fixed protocol must be preregistered as an ML experiment; reported runs require
clean source and save a fresh UUID directory under `reports_out/hourly_calibration`.

The map, raw/calibrated probabilities, ten-bin reliability curve, Brier score and
log loss are saved with source/config/snapshot hashes and a calibration SVG.
These are **same-row resubstitution diagnostics**, not independent scores. The
classifier also used VALID to select its stopping iteration. A more diagonal
curve does not prove stronger unseen prediction or profitable execution.
The frozen map is available only after the accepted VALID closing boundary;
it cannot authorize trades retrospectively inside its fitting period.

Run `scripts/calibrate_hourly.py --source SOURCE_METRICS --experiment-id ID`.
Plot generation uses matplotlib from the existing notebooks dependency group.
The calibration follows the [scikit-learn calibration guide](https://scikit-learn.org/stable/modules/calibration.html).

Step 137 freezes each symbol's conditional positive/nonpositive forward-return
means from TRAIN only. Expected signed edge in basis points is
`p * mean_positive + (1-p) * mean_nonpositive`. The default cost is a complete
entry/exit: twice the accepted per-side taker fee plus slippage. Subtract it from
the edge magnitude, preserving its sign and setting an inside-cost edge to zero.
This is an expected-edge assumption, not measured fill cost or P&L.

Apply the existing trailing sample z-score over 168 observed hourly rows, then
clip to [-1,1]. A window containing an absent hour, non-finite probability or
zero variance stays unavailable. Normalisation cannot reverse the net expected
edge or create an inside-cost trade. Each AlphaValue is stamped at bar close and
carries the full calibration/payoff/fee policy hash, source model and snapshot.
Before the fitted map's availability boundary, AlphaValues are UNAVAILABLE;
retrospective diagnostic values are saved separately and cannot be submitted to
a strategy. This prevents full-VALID calibration from becoming look-ahead trades.

`scripts/build_hourly_ml_alpha.py --calibration METRICS --experiment-id ID` verifies
the calibration artifacts, loads the original paired TRAIN observations without
refitting the classifier, and saves policy, AlphaValues, edge diagnostics with
and without cost, and hashes in a fresh UUID directory. No labels are read by the
transformation. All existing VALID predictions predate map availability; their
diagnostics are development evidence. Registering and evaluating this ML alpha
through the simulator and gates belongs to step 145.
