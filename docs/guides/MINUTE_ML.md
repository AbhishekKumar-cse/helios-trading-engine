# Fixed minute ML pipeline (158)

Experiment **5628** was preregistered from clean `75cc995` before implementation
or minute ML measurements. Its fixed BTCUSDT/1m feature/label protocol uses the
accepted minute TRAIN/VALID windows and step-156 snapshot. All prior hourly and
minute quantitative results and cost curves were declared known.

There is one LightGBM configuration, seed 0, eight existing features, 500 maximum
trees, 31 leaves and 50-round binary-logloss early stopping on VALID. TRAIN alone
fits the model and positive/nonpositive return magnitudes. The existing VALID
isotonic map and 168-bar trailing alpha transform are reused with one-minute
timestamps, accepted fees and two cost sides. No parameter or seed search occurs.

The source model, predictions, calibration, typed alpha and final evaluation are
hash-linked, retained outside Git and journalled after each stage. A consumed
attempt or existing output directory cannot be rerun automatically. Run once,
after committing implementation, with:

```bash
/home/abhi/.venvs/helios/bin/python scripts/run_minute_ml.py --experiment-id 5628
```

Calibration becomes available only after VALID ends. Historical VALID typed
values therefore remain UNAVAILABLE even where retrospective diagnostic alpha
can be calculated. The common minute simulator, cost model, validity and G1–G6
receive those statuses unchanged. Predictive metrics and calibration diagnostics
are development evidence; they never substitute for actionable alpha or net P&L.
No TEST data, promotion or real order route is used.

The shared hourly policy schema and hashes are preserved. Tests cover minute
calibration bounds, the frozen minute-to-bar timestamp mapping, rejection of
family mismatches, and the existing hourly calibration/alpha regressions.
