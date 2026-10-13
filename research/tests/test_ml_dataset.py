"""Exact feature/forward-label alignment, masks, gaps and feature-store loading."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from helios.features.runner import FeatureFrame
from helios.ml.dataset import (
    HOUR_US,
    DatasetConfig,
    DatasetError,
    build_dataset,
    load_feature_frame,
)


def fixture(symbol="BTCUSDT", offset=0):
    times = np.arange(6, dtype=np.int64) * HOUR_US + offset
    frame = FeatureFrame(
        symbol,
        pd.Series(times, index=range(10, 16)),
        pd.DataFrame({"momentum": [np.nan, 20.0, 30.0, 40.0, 50.0, 60.0]}, index=range(10, 16)),
        pd.DataFrame({"momentum": [False, True, True, True, True, True]}, index=range(10, 16)),
    )
    bars = pd.DataFrame(
        {"open_time": times, "close": 100 * 1.1 ** np.arange(6)}, index=range(100, 106)
    )
    return frame, bars


def dataset(frame, bars, horizon=2):
    return build_dataset(
        {frame.symbol: frame},
        {frame.symbol: bars},
        config=DatasetConfig(features=("momentum",), horizon=horizon),
        snapshot_id="fixture-snapshot",
    )


def test_exact_horizon_labels_timestamp_alignment_and_counts() -> None:
    frame, bars = fixture()
    result = dataset(frame, bars)
    assert [s.open_time for s in result.samples] == [HOUR_US, 2 * HOUR_US, 3 * HOUR_US]
    assert [s.label_end_time for s in result.samples] == [3 * HOUR_US, 4 * HOUR_US, 5 * HOUR_US]
    np.testing.assert_allclose(result.X[:, 0], [20, 30, 40])
    np.testing.assert_allclose(result.y, [0.21] * 3)
    count = result.counts[0]
    assert (
        count.n_rows,
        count.n_feature_unavailable,
        count.n_label_unavailable,
        count.n_usable,
    ) == (6, 1, 2, 3)
    assert len(result.config_hash) == len(result.input_hashes[0][1]) == 64
    copy = result.X
    copy[0, 0] = 999
    assert result.X[0, 0] == 20
    assert result.snapshot_id == "fixture-snapshot"


def test_future_price_perturbation_leaves_earlier_samples_unchanged() -> None:
    frame, bars = fixture()
    before = dataset(frame, bars)
    bars.iloc[-1, bars.columns.get_loc("close")] *= 3
    after = dataset(frame, bars)
    assert before.samples[:2] == after.samples[:2]
    assert before.samples[-1].target != after.samples[-1].target
    np.testing.assert_array_equal(before.X, after.X)
    assert before.input_hashes != after.input_hashes


def test_missing_intervals_and_feature_rows_do_not_make_shorter_labels() -> None:
    frame, bars = fixture()
    bars = bars.iloc[[0, 1, 3, 4, 5]]
    frame = replace(
        frame,
        open_time=frame.open_time.iloc[[0, 1, 3, 4, 5]],
        values=frame.values.iloc[[0, 1, 3, 4, 5]],
        available=frame.available.iloc[[0, 1, 3, 4, 5]],
    )
    result = dataset(frame, bars)
    assert [s.open_time for s in result.samples] == [3 * HOUR_US]
    frame = replace(
        frame,
        open_time=frame.open_time.iloc[[0, 1, 3, 4]],
        values=frame.values.iloc[[0, 1, 3, 4]],
        available=frame.available.iloc[[0, 1, 3, 4]],
    )
    assert not dataset(frame, bars).samples


def test_multi_coin_samples_are_chronological_with_symbol_tie_break() -> None:
    btc, btc_bars = fixture()
    eth, eth_bars = fixture("ETHUSDT")
    config = DatasetConfig(features=("momentum",))
    first = build_dataset(
        {"ETHUSDT": eth, "BTCUSDT": btc}, {"ETHUSDT": eth_bars, "BTCUSDT": btc_bars}, config=config
    )
    second = build_dataset(
        {"BTCUSDT": btc, "ETHUSDT": eth}, {"BTCUSDT": btc_bars, "ETHUSDT": eth_bars}, config=config
    )
    assert first == second
    assert [(s.open_time, s.symbol) for s in first.samples] == sorted(
        (s.open_time, s.symbol) for s in first.samples
    )


@pytest.mark.parametrize(
    "change",
    [
        {"horizon": True},
        {"horizon": 0},
        {"features": ("momentum", "momentum")},
        {"features": ("close;DROP",)},
    ],
)
def test_configuration_rejects_invalid_horizons_and_names(change) -> None:
    with pytest.raises(ValidationError):
        DatasetConfig.model_validate({"features": ("momentum",)} | change)


def test_known_nonfinite_features_bad_prices_and_masks_are_refused() -> None:
    frame, bars = fixture()
    frame.values.iloc[1, 0] = np.inf
    with pytest.raises(DatasetError, match="finite"):
        dataset(frame, bars)
    frame.values.iloc[1, 0] = 20
    bars.iloc[1, bars.columns.get_loc("close")] = 0
    with pytest.raises(DatasetError, match="positive"):
        dataset(frame, bars)
    frame, bars = fixture()
    frame.available["momentum"] = 1
    with pytest.raises(DatasetError, match="boolean"):
        dataset(frame, bars)


def test_loads_existing_parquet_feature_store_columns_and_explicit_range(tmp_path: Path) -> None:
    frame, _ = fixture()
    destination = (
        tmp_path
        / "feature_set=v1"
        / "interval=1h"
        / "symbol=BTCUSDT"
        / "year=1970"
        / "features.parquet"
    )
    destination.parent.mkdir(parents=True)
    exported = pd.DataFrame(
        {
            "open_time": frame.open_time.to_numpy(),
            "momentum": frame.values.momentum.to_numpy(),
            "available__momentum": frame.available.momentum.to_numpy(),
        }
    )
    exported.to_parquet(destination, index=False)
    loaded = load_feature_frame(
        "BTCUSDT",
        HOUR_US,
        3 * HOUR_US,
        config=DatasetConfig(features=("momentum",)),
        feature_dir=tmp_path,
    )
    assert loaded.rows == 3 and loaded.available.momentum.all()
    assert loaded.values.momentum.tolist() == [20, 30, 40]
    with pytest.raises(DatasetError, match="bounds"):
        load_feature_frame(
            "BTCUSDT",
            None,
            None,
            config=DatasetConfig(features=("momentum",)),
            feature_dir=tmp_path,
        )


def test_empty_usable_dataset_has_correct_shapes_and_unavailable_prices_counted() -> None:
    frame, bars = fixture()
    result = dataset(frame, bars, horizon=99)
    assert result.X.shape == (0, 1) and result.y.shape == (0,)
    bars.iloc[2, bars.columns.get_loc("close")] = np.nan
    assert dataset(frame, bars).counts[0].n_label_unavailable == 4
