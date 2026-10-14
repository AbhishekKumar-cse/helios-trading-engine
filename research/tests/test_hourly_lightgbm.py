import json
from dataclasses import replace

import joblib
import numpy as np
import pytest
from test_hourly_baselines import pair

from helios.ml.dataset import DatasetError
from helios.ml.hourly_baselines import save_baseline_run
from helios.ml.hourly_lightgbm import LightGBMConfig, fit_lightgbm
from helios.registry.results import Split
from helios.sim.splits import split_window


def fixture():
    config, train, valid = pair()
    return (
        LightGBMConfig(
            dataset=config.dataset,
            symbols=config.symbols,
            n_estimators=30,
            stopping_rounds=3,
            min_child_samples=3,
        ),
        train,
        valid,
    )


def test_fixed_seed_early_stopping_and_saved_predictions(tmp_path):
    config, train, valid = fixture()
    one = fit_lightgbm(train, valid, config, reported=False)
    two = fit_lightgbm(train, valid, config, reported=False)
    assert 0 < one.report["best_iteration"] <= config.n_estimators
    np.testing.assert_array_equal(
        one.predictions.probability_positive, two.predictions.probability_positive
    )
    path = save_baseline_run(one, tmp_path)
    model = joblib.load(path.parent / "lightgbm.joblib")
    np.testing.assert_allclose(
        model.predict_proba(valid.dataset.X)[:, 1], one.predictions.probability_positive
    )
    assert json.loads(path.read_text())["protocol"]["test_access"] is False


@pytest.mark.leakage
def test_test_partition_refused_before_training():
    config, train, valid = fixture()
    valid = replace(valid, window=split_window(Split.TEST, interval="1h"))
    with pytest.raises(DatasetError, match="TEST"):
        fit_lightgbm(train, valid, config, reported=False)
