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
