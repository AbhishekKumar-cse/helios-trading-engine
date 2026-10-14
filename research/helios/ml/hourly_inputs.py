"""Snapshot-verified, explicitly counted TRAIN/VALID hourly ML inputs (125)."""

import json
from dataclasses import replace
from typing import Any

import numpy as np
import pandas as pd

from helios.data.bars import DEFAULT_OUT_DIR
from helios.data.binance import sha256_file
from helios.data.loader import load_bars
from helios.data.snapshots import compute_snapshot_id, load_manifest
from helios.features.runner import FeatureFrame
from helios.features.store import DEFAULT_FEATURE_DIR
from helios.ml.dataset import HOUR_US, DatasetError, build_dataset, load_feature_frame
from helios.ml.hourly_baselines import HourlyBaselineConfig
from helios.ml.splits import SplitDataset, dataset_for_split
from helios.registry.results import Split
from helios.sim.splits import split_window


def eligible_rows(
    features: FeatureFrame, bars: pd.DataFrame
) -> tuple[FeatureFrame, pd.DataFrame, dict[str, int]]:
    resolution = np.where(bars.close_time.to_numpy() % 1000 == 0, 1000, 1)
    on_grid = bars.open_time % HOUR_US == 0
    complete = bars.close_time + resolution == bars.open_time + HOUR_US
    selected = bars.loc[on_grid & complete].copy()
    mask = features.open_time.isin(selected.open_time)
    filtered = replace(
        features,
        open_time=features.open_time.loc[mask].copy(),
        values=features.values.loc[mask].copy(),
        available=features.available.loc[mask].copy(),
    )
    counts = dict(
        n_raw_bars=len(bars),
        n_off_grid=int((~on_grid).sum()),
        n_incomplete_on_grid=int((on_grid & ~complete).sum()),
        n_eligible_bars=len(selected),
        n_raw_feature_rows=len(features.open_time),
        n_excluded_feature_rows=int((~mask).sum()),
    )
    return filtered, selected, counts


def load_hourly_pair(
    snapshot_id: str, config: HourlyBaselineConfig
) -> tuple[SplitDataset, SplitDataset, dict[str, Any]]:
    """No TEST argument exists. Hash selected files before querying explicit bounds."""
    snapshot = load_manifest(snapshot_id)
    if (
        not snapshot.files
        or compute_snapshot_id(snapshot.files) != snapshot_id
        or snapshot.snapshot_id != snapshot_id
        or snapshot.interval != "1h"
        or not set(config.symbols).issubset(snapshot.symbols)
    ):
        raise DatasetError("ML snapshot identity, universe or interval mismatch")
    windows = [
        split_window(split, interval="1h", horizon_periods=config.dataset.horizon)
        for split in (Split.TRAIN, Split.VALID)
    ]
    years = range(
        pd.Timestamp(windows[0].start_us, unit="us").year,
        pd.Timestamp(windows[-1].end_us - 1, unit="us").year + 1,
    )
    registered = {f.path: f.sha256 for f in snapshot.files}
    for file in snapshot.files:
        if any(f"symbol={s}/" in file.path for s in config.symbols) and any(
            f"year={y}/" in file.path for y in years
        ):
            path = (DEFAULT_OUT_DIR / file.path).resolve()
            if (
                not path.is_relative_to(DEFAULT_OUT_DIR.resolve())
                or sha256_file(path) != file.sha256
            ):
                raise DatasetError("ML bar snapshot checksum mismatch")
    provenance = {}
    for symbol in config.symbols:
        root = (
            DEFAULT_FEATURE_DIR
            / f"feature_set={config.dataset.feature_set_version}"
            / "interval=1h"
            / f"symbol={symbol}"
        )
        path = root / "manifest.json"
        manifest = json.loads(path.read_text())
        if any(
            registered.get(f["path"]) != f["sha256"] for f in manifest["input_snapshot"]["files"]
        ):
            raise DatasetError("ML feature source does not match bars snapshot")
        for file in manifest["files"]:
            if any(f"year={y}/" in file["path"] for y in years):
                feature_path = (root / file["path"]).resolve()
                if (
                    not feature_path.is_relative_to(root.resolve())
                    or sha256_file(feature_path) != file["sha256"]
                ):
                    raise DatasetError("ML feature checksum mismatch")
        provenance[symbol] = dict(manifest_sha256=sha256_file(path), lineage=manifest["lineage"])
    parts = []
    exclusions = {}
    for window in windows:
        features, prices, counts = {}, {}, {}
        for symbol in config.symbols:
            frame = load_feature_frame(
                symbol, window.start_us, window.end_us - 1, config=config.dataset
            )
            bars = load_bars(symbol, "1h", window.start_us, window.end_us - 1)
            features[symbol], prices[symbol], counts[symbol] = eligible_rows(frame, bars)
        parent = build_dataset(features, prices, config=config.dataset, snapshot_id=snapshot_id)
        parts.append(dataset_for_split(parent, window))
        exclusions[window.split.name] = counts
    return parts[0], parts[1], dict(feature_provenance=provenance, exclusions=exclusions)
