import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import accuracy_score, mean_squared_error

from helios.common.lineage import LineageError
from helios.data.binance import sha256_file
from helios.features.runner import FeatureFrame
from helios.ml.dataset import HOUR_US, DatasetConfig, DatasetError, build_dataset
from helios.ml.hourly_baselines import HourlyBaselineConfig, fit_hourly_baselines, save_baseline_run
from helios.ml.hourly_inputs import eligible_rows, load_hourly_pair
from helios.ml.splits import dataset_for_split
from helios.registry.results import Split
from helios.sim.splits import split_window


def pair():
    config = HourlyBaselineConfig(
        dataset=DatasetConfig(features=("fixture",)), symbols=("BTCUSDT",)
    )
    parts = []
    for split in (Split.TRAIN, Split.VALID):
        window = split_window(split, interval="1h")
        times = window.start_us + np.arange(40, dtype=np.int64) * HOUR_US
        x = np.sin(np.arange(40) * 1.1)
        prices = [100.0]
        for value in x[:-1]:
            prices.append(prices[-1] * (1 + value * 0.01))
        feature = FeatureFrame(
            "BTCUSDT",
            pd.Series(times),
            pd.DataFrame(dict(fixture=x)),
            pd.DataFrame(dict(fixture=np.ones(40, dtype=bool))),
        )
        bars = pd.DataFrame(dict(open_time=times, close=prices))
        parent = build_dataset(
            {"BTCUSDT": feature}, {"BTCUSDT": bars}, config=config.dataset, snapshot_id="fixture"
        )
        parts.append(dataset_for_split(parent, window))
    return config, parts[0], parts[1]


@pytest.mark.leakage
def test_valid_perturbations_cannot_change_training_scaler_or_models():
    config, train, valid = pair()
    first = fit_hourly_baselines(train, valid, config, reported=False)
    changed = replace(
        valid,
        dataset=replace(
            valid.dataset,
            samples=tuple(
                replace(s, features=(s.features[0] + 1000,), target=-s.target)
                for s in valid.dataset.samples
            ),
        ),
    )
    second = fit_hourly_baselines(train, changed, config, reported=False)
    for name in first.models:
        np.testing.assert_array_equal(
            first.models[name].named_steps["model"].coef_,
            second.models[name].named_steps["model"].coef_,
        )
        np.testing.assert_allclose(
            first.models[name].named_steps["scale"].mean_, train.dataset.X.mean(axis=0)
        )
    assert (
        first.report["datasets"]["VALID"]["sample_sha256"]
        != second.report["datasets"]["VALID"]["sample_sha256"]
    )


def test_metrics_recompute_and_checkpoint_hashes_round_trip(tmp_path: Path):
    config, train, valid = pair()
    run = fit_hourly_baselines(train, valid, config, reported=False)
    assert run.report["ridge"]["rmse"] == pytest.approx(
        np.sqrt(mean_squared_error(valid.dataset.y, run.predictions.ridge_return))
    )
    assert run.report["logistic"]["accuracy"] == accuracy_score(
        valid.dataset.y > 0, run.predictions.direction_predicted
    )
    one = save_baseline_run(run, tmp_path)
    two = save_baseline_run(run, tmp_path)
    assert one != two and one.read_bytes() == two.read_bytes()
    stored = json.loads(one.read_text())
    for name, digest in stored["artifact_hashes"].items():
        assert sha256_file(one.parent / name) == digest
    model = joblib.load(one.parent / "ridge.joblib")
    np.testing.assert_allclose(model.predict(valid.dataset.X), run.predictions.ridge_return)
    assert pd.read_parquet(one.parent / "valid_predictions.parquet").shape[0] == len(
        valid.dataset.samples
    )


@pytest.mark.parametrize("problem", ["TEST", "boundary", "config", "snapshot", "one_class"])
def test_invalid_partitions_refused_before_model_fit(problem):
    config, train, valid = pair()
    if problem == "TEST":
        valid = replace(valid, window=split_window(Split.TEST, interval="1h"))
    if problem == "boundary":
        samples = list(train.dataset.samples)
        samples[-1] = replace(samples[-1], label_end_time=train.window.end_us)
        train = replace(train, dataset=replace(train.dataset, samples=tuple(samples)))
    if problem == "config":
        config = HourlyBaselineConfig()
    if problem == "snapshot":
        valid = replace(valid, dataset=replace(valid.dataset, snapshot_id="different"))
    if problem == "one_class":
        train = replace(
            train,
            dataset=replace(
                train.dataset,
                samples=tuple(
                    replace(s, target=abs(s.target) + 0.001) for s in train.dataset.samples
                ),
            ),
        )
    with pytest.raises(DatasetError):
        fit_hourly_baselines(train, valid, config, reported=False)


def test_reported_dirty_source_fails_before_estimator_fit():
    config, train, valid = pair()
    with patch("helios.ml.hourly_baselines.RunContext.capture", side_effect=LineageError("dirty")):
        with pytest.raises(LineageError):
            fit_hourly_baselines(train, valid, config)


def test_complete_grid_policy_counts_exclusions_without_filling_gaps():
    times = pd.Series([0, HOUR_US, 2 * HOUR_US + 1, 3 * HOUR_US])
    frame = FeatureFrame(
        "BTCUSDT", times, pd.DataFrame(dict(x=[1, 2, 3, 4])), pd.DataFrame(dict(x=[True] * 4))
    )
    bars = pd.DataFrame(
        dict(
            open_time=times,
            close_time=[HOUR_US - 1000, 2 * HOUR_US + 475000, 3 * HOUR_US, 4 * HOUR_US - 1000],
            close=[100.0] * 4,
        )
    )
    features, prices, counts = eligible_rows(frame, bars)
    assert prices.open_time.tolist() == features.open_time.tolist() == [0, 3 * HOUR_US]
    assert counts["n_off_grid"] == counts["n_incomplete_on_grid"] == 1
    assert counts["n_excluded_feature_rows"] == 2


def test_snapshot_mismatch_prevents_any_observation_load():
    with (
        patch("helios.ml.hourly_inputs.load_manifest") as manifest,
        patch("helios.ml.hourly_inputs.load_bars") as loader,
    ):
        manifest.return_value.files = []
        with pytest.raises(DatasetError, match="snapshot"):
            load_hourly_pair("wrong", HourlyBaselineConfig())
        loader.assert_not_called()
