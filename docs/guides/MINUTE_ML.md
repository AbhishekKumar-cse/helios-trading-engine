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

## Retained outcome (2026-10-15)

The clean `2f45359ac272cc39ac7db3f412be6f9774dd0d5c` attempt finished and
stored run `efec729e-e04f-4d7c-b726-c3b99b307b12`, **INVALID** with
`UNAVAILABLE_AFTER_WARMUP`. TRAIN has 525,432 usable samples, VALID 259,199.
The fixed stopping rule selected iteration 73. Predictive VALID accuracy is
0.522807 versus TRAIN-majority accuracy 0.519061; macro-F1 is 0.506538 and AUC
0.534570. These are development metrics, without an independent performance claim.

All 259,199 typed values are UNAVAILABLE; zero diagnostic alpha values are
finite. Calibration availability is enforced, and the fixed cost-adjusted
transform supplies no usable trading series. No retrospective signals are
substituted. No trading performance, gate pass or promotion is claimed. The
companion [`minute_ml_results.json`](../research/minute_ml_results.json) records
the source/model/calibration/alpha/evaluation hashes and precise validity counts.
Verification confirmed clean lineage, preregistration before measurement, all
child artifact hashes and zero global TEST accesses. The 38 focused ML tests and
strict package typing pass.
