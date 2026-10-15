"""Purge forward labels and exclude embargo rows; authorize before TEST loading (115)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace

import pandas as pd
from sqlalchemy import Engine

from helios.common.project_config import SplitsConfig, load_splits
from helios.data.klines import interval_us
from helios.features.runner import FeatureFrame
from helios.ml.dataset import DatasetConfig, DatasetError, HourlyDataset, build_dataset
from helios.registry.experiments import require_open_experiment
from helios.registry.results import Split
from helios.registry.test_access import TestSetAccess
from helios.sim.positions import _times
from helios.sim.splits import SplitWindow, _authorize, split_window


@dataclass(frozen=True)
class SplitDataset:
    window: SplitWindow
    dataset: HourlyDataset
    n_input_samples: int
    n_outside_split: int
    n_purged_labels: int
    test_access: TestSetAccess | None


def dataset_for_split(
    dataset: HourlyDataset,
    window: SplitWindow,
    *,
    test_access: TestSetAccess | None = None,
    alpha_id: str | None = None,
    version: int | None = None,
) -> SplitDataset:
    """Partition already-authorized data. This function never loads a dataset.

    Source availability counts/hashes remain those of the parent dataset;
    split-specific outside/purged counts are separate, never relabelled as warm-up.
    """
    configured = SplitsConfig.model_validate_json(window.splits_json)
    expected = split_window(
        window.split,
        interval=dataset.config.interval,
        horizon_periods=dataset.config.horizon,
        splits=configured,
    )
    if window != expected:
        raise DatasetError("dataset horizon/interval or split configuration mismatch")
    if window.split is Split.TEST:
        if (
            test_access is None
            or dataset.snapshot_id is None
            or (test_access.alpha_id, test_access.version, test_access.snapshot_id)
            != (alpha_id, version, dataset.snapshot_id)
        ):
            raise DatasetError("TEST partition requires its matching access reservation")
    kept, outside, purged = [], 0, 0
    for sample in dataset.samples:
        if sample.label_end_time - sample.open_time != dataset.config.horizon * interval_us(
            dataset.config.interval
        ):
            raise DatasetError("sample label window does not match the configured horizon")
        if not window.start_us <= sample.open_time < window.end_us:
            outside += 1
        elif sample.label_end_time >= window.end_us:
            purged += 1
        else:
            kept.append(sample)
    return SplitDataset(
        window,
        replace(dataset, samples=tuple(kept)),
        len(dataset.samples),
        outside,
        purged,
        test_access,
    )


DatasetLoader = Callable[
    [SplitWindow], tuple[Mapping[str, FeatureFrame], Mapping[str, pd.DataFrame]]
]


def build_split_dataset(
    engine: Engine,
    *,
    experiment_id: int,
    alpha_id: str,
    version: int,
    split: Split,
    config: DatasetConfig,
    load_inputs: DatasetLoader,
    splits: SplitsConfig | None = None,
    actor: str = "",
    purpose: str = "",
) -> SplitDataset:
    """Commit TEST reservation before invoking the trusted, range-aware input loader.

    Price/feature inputs can include earlier causal history but never timestamps
    past the requested split end. Hence boundary-crossing labels are unavailable
    without reading the following split or embargo. No normalization is fitted.
    """
    selected = load_splits() if splits is None else SplitsConfig.model_validate(splits.model_dump())
    config = DatasetConfig.model_validate(config.model_dump())
    window = split_window(
        split, interval=config.interval, horizon_periods=config.horizon, splits=selected
    )
    with engine.begin() as connection:
        access = _authorize(
            connection,
            window,
            experiment_id=experiment_id,
            alpha_id=alpha_id,
            version=version,
            actor=actor,
            purpose=purpose,
        )
        snapshot_id = require_open_experiment(connection, experiment_id).snapshot_id
    features, bars = load_inputs(window)
    for frame in features.values():
        if (_times(frame.open_time) >= window.end_us).any():
            raise DatasetError("features extend beyond the authorized split end")
    for prices in bars.values():
        if "open_time" not in prices or (_times(prices.open_time) >= window.end_us).any():
            raise DatasetError("prices extend beyond the authorized split end")
    dataset = build_dataset(features, bars, config=config, snapshot_id=snapshot_id)
    return dataset_for_split(
        dataset, window, test_access=access, alpha_id=alpha_id, version=version
    )
