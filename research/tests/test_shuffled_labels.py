"""Planted-signal positive control and shuffled-label null, synthetic data only (146)."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from helios.features.runner import FeatureFrame
from helios.ml.dataset import HOUR_US, DatasetConfig, build_dataset
from helios.ml.hourly_baselines import HourlyBaselineConfig, fit_hourly_baselines
from helios.ml.hourly_lightgbm import LightGBMConfig, fit_lightgbm
from helios.ml.splits import dataset_for_split
from helios.registry.results import Split
from helios.sim.splits import split_window

N = 2048
SEEDS = tuple(range(10))
CHANCE_TOLERANCE = 0.05  # fixed before running; aggregate accuracy and AUROC


def synthetic_pair():
    rng = np.random.default_rng(146)
    config = HourlyBaselineConfig(
        dataset=DatasetConfig(features=("signal", "noise")), symbols=("BTCUSDT",)
    )
    parts = []
    for split in (Split.TRAIN, Split.VALID):
        window = split_window(split, interval="1h")
        x = rng.normal(size=(N + 1, 2))
        times = pd.Series(window.start_us + np.arange(N + 1, dtype=np.int64) * HOUR_US)
        # Deliberately learnable fixture: observed x[t] determines the following
        # synthetic return. No real market series or future feature is involved.
        prices = np.r_[100.0, 100 * np.cumprod(1 + np.where(x[:-1, 0] > 0, 0.001, -0.001))]
        features = FeatureFrame(
            "BTCUSDT",
            times,
            pd.DataFrame(x, columns=config.dataset.features),
            pd.DataFrame(True, index=range(N + 1), columns=config.dataset.features),
        )
        parent = build_dataset(
            {"BTCUSDT": features},
            {"BTCUSDT": pd.DataFrame(dict(open_time=times, close=prices))},
            config=config.dataset,
            snapshot_id="synthetic-shuffled-control-v1",
        )
        parts.append(dataset_for_split(parent, window))
    return config, parts[0], parts[1]


@pytest.mark.leakage
@pytest.mark.parametrize("classifier", ["logistic", "lightgbm"])
def test_shuffled_labels_score_at_chance_in_existing_ml_pipelines(classifier):
    config, train, valid = synthetic_pair()
    original_train, original_valid = train.dataset.y.copy(), valid.dataset.y.copy()

    def metrics(training, validation):
        if classifier == "lightgbm":
            run = fit_lightgbm(
                training,
                validation,
                LightGBMConfig(
                    dataset=config.dataset,
                    symbols=config.symbols,
                ),
                reported=False,
            )
            return run.report["metrics"]
        return fit_hourly_baselines(training, validation, config, reported=False).report["logistic"]

    positive = metrics(train, valid)
    assert positive["accuracy"] > 0.97 and positive["roc_auc"] > 0.99
    scores = []
    for seed in SEEDS:
        rng = np.random.default_rng(seed)
        shuffled = []
        for part in (train, valid):
            # Separate within-split permutations retain X, chronology, label
            # windows and class counts. No row crosses a purge/embargo boundary.
            targets = rng.permutation(part.dataset.y)
            changed = replace(
                part,
                dataset=replace(
                    part.dataset,
                    samples=tuple(
                        replace(sample, target=float(target))
                        for sample, target in zip(part.dataset.samples, targets, strict=True)
                    ),
                ),
            )
            np.testing.assert_array_equal(changed.dataset.X, part.dataset.X)
            np.testing.assert_array_equal(np.sort(targets), np.sort(part.dataset.y))
            shuffled.append(changed)
        scores.append(metrics(*shuffled))
    for metric in ("accuracy", "roc_auc"):
        mean = float(np.mean([score[metric] for score in scores]))
        assert abs(mean - 0.5) < CHANCE_TOLERANCE, (classifier, metric, mean)
        print(f"synthetic shuffled {classifier} mean {metric}={mean:.8f}; seeds={SEEDS}")
    np.testing.assert_array_equal(train.dataset.y, original_train)
    np.testing.assert_array_equal(valid.dataset.y, original_valid)
