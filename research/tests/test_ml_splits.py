"""Boundary purging, embargo exclusion and pre-load TEST accounting."""

from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import Connection, Engine
from test_ml_dataset import dataset, fixture
from test_test_access import ALPHA, SNAPSHOT_ID
from test_test_access import registry as _registry_fixture

from helios.common.project_config import HorizonFamily, SplitsConfig
from helios.ml.dataset import HOUR_US, DatasetConfig, DatasetError
from helios.ml.splits import build_split_dataset, dataset_for_split
from helios.registry.experiments import register_experiment
from helios.registry.results import Split
from helios.registry.test_access import TestSetLimitReached as BudgetExhausted
from helios.registry.test_access import count_test_accesses
from helios.sim.positions import SimulationError
from helios.sim.splits import split_window

registry = pytest.fixture(_registry_fixture.__wrapped__)


def splits():
    return SplitsConfig.model_validate(
        {
            "version": "fixture",
            "families": {
                HorizonFamily.HOURLY: {
                    "periods_per_year": 8760,
                    "embargo_days": 1,
                    "train": {"start": "1970-01-01", "end": "1970-01-01"},
                    "valid": {"start": "1970-01-03", "end": "1970-01-03"},
                    "test": {"start": "1970-01-05", "end": "1970-01-05"},
                }
            },
        }
    )


@pytest.mark.leakage
def test_label_at_exact_split_end_is_purged_and_all_kept_windows_stay_inside() -> None:
    frame, bars = fixture(offset=20 * HOUR_US)
    parent = dataset(frame, bars)
    window = split_window(Split.TRAIN, interval="1h", horizon_periods=2, splits=splits())
    result = dataset_for_split(parent, window)
    assert len(result.dataset.samples) == 1
    assert result.n_input_samples == 3 and result.n_purged_labels == 2
    assert all(
        window.start_us <= s.open_time < s.label_end_time < window.end_us
        for s in result.dataset.samples
    )
    assert (
        result.dataset.input_hashes == parent.input_hashes
        and result.dataset.counts == parent.counts
    )
    assert len(parent.samples) == 3


@pytest.mark.leakage
def test_embargo_rows_are_not_assigned_to_either_split() -> None:
    frame, bars = fixture(offset=24 * HOUR_US)
    parent = dataset(frame, bars)
    for split in (Split.TRAIN, Split.VALID):
        window = split_window(split, interval="1h", horizon_periods=2, splits=splits())
        result = dataset_for_split(parent, window)
        assert not result.dataset.samples and result.n_outside_split == len(parent.samples)


@pytest.mark.leakage
def test_extra_future_prices_cannot_change_kept_training_labels() -> None:
    frame, bars = fixture(offset=20 * HOUR_US)
    window = split_window(Split.TRAIN, interval="1h", horizon_periods=2, splits=splits())
    before = dataset_for_split(dataset(frame, bars), window)
    bars.iloc[-2:, bars.columns.get_loc("close")] *= 10
    after = dataset_for_split(dataset(frame, bars), window)
    assert before.dataset.samples == after.dataset.samples
    assert before.dataset.input_hashes != after.dataset.input_hashes


def test_inadequate_embargo_and_forged_window_or_label_fail() -> None:
    with pytest.raises(SimulationError, match="embargo"):
        split_window(Split.TRAIN, interval="1h", horizon_periods=25, splits=splits())
    frame, bars = fixture(offset=20 * HOUR_US)
    parent = dataset(frame, bars)
    window = split_window(Split.TRAIN, interval="1h", horizon_periods=2, splits=splits())
    with pytest.raises(DatasetError, match="mismatch"):
        dataset_for_split(parent, replace(window, end_us=window.end_us + HOUR_US))
    bad = replace(
        parent, samples=(replace(parent.samples[0], label_end_time=parent.samples[0].open_time),)
    )
    with pytest.raises(DatasetError, match="horizon"):
        dataset_for_split(bad, window)


def test_test_partition_requires_reservation() -> None:
    frame, bars = fixture(offset=100 * HOUR_US)
    parent = dataset(frame, bars)
    window = split_window(Split.TEST, interval="1h", horizon_periods=2, splits=splits())
    with pytest.raises(DatasetError, match="reservation"):
        dataset_for_split(parent, window)


def test_range_guard_refuses_future_prices_without_silently_trimming() -> None:
    engine = MagicMock(spec=Engine)
    frame, bars = fixture(offset=20 * HOUR_US)
    with (
        patch("helios.ml.splits._authorize", return_value=None),
        patch(
            "helios.ml.splits.require_open_experiment",
            return_value=SimpleNamespace(snapshot_id="fixture"),
        ),
    ):
        with pytest.raises(DatasetError, match="authorized"):
            build_split_dataset(
                engine,
                experiment_id=1,
                alpha_id="example",
                version=1,
                split=Split.TRAIN,
                config=DatasetConfig(features=("momentum",), horizon=2),
                splits=splits(),
                load_inputs=lambda w: ({frame.symbol: frame}, {frame.symbol: bars}),
            )


def test_test_reservation_commits_before_loader_and_exhaustion_prevents_loading() -> None:
    events = []

    class EngineStub:
        @contextmanager
        def begin(self):
            yield MagicMock()
            events.append("commit")

    loader = MagicMock(side_effect=RuntimeError("loader stopped"))
    with (
        patch("helios.ml.splits._authorize", side_effect=lambda *a, **k: events.append("reserve")),
        patch(
            "helios.ml.splits.require_open_experiment",
            return_value=SimpleNamespace(snapshot_id="fixture"),
        ),
    ):
        with pytest.raises(RuntimeError, match="loader"):
            build_split_dataset(
                EngineStub(),
                experiment_id=1,
                alpha_id="example",
                version=1,
                split=Split.TEST,
                config=DatasetConfig(features=("momentum",)),
                splits=splits(),
                load_inputs=loader,
            )
    assert events == ["reserve", "commit"] and loader.call_count == 1
    loader.reset_mock()
    with patch("helios.ml.splits._authorize", side_effect=BudgetExhausted("third access")):
        with pytest.raises(BudgetExhausted):
            build_split_dataset(
                EngineStub(),
                experiment_id=1,
                alpha_id="example",
                version=1,
                split=Split.TEST,
                config=DatasetConfig(features=("momentum",)),
                splits=splits(),
                load_inputs=loader,
            )
    loader.assert_not_called()


def test_public_builder_real_database_test_budget_and_kept_windows(registry: Connection) -> None:
    experiment = register_experiment(
        registry,
        hypothesis="Synthetic ML purge verification",
        author="test",
        snapshot_id=SNAPSHOT_ID,
    )
    # Engine transaction contexts reuse the rolled-back PostgreSQL fixture here;
    # commit ordering is tested separately without inserting persistent test rows.
    engine = MagicMock(spec=Engine)
    engine.begin.return_value.__enter__.return_value = registry

    def load(window):
        frame, bars = fixture(offset=window.start_us)
        return {frame.symbol: frame}, {frame.symbol: bars}

    for count in (1, 2):
        result = build_split_dataset(
            engine,
            experiment_id=experiment.experiment_id,
            alpha_id=ALPHA,
            version=1,
            split=Split.TEST,
            config=DatasetConfig(features=("momentum",)),
            load_inputs=load,
            actor="test",
            purpose="Synthetic ML split verification",
        )
        assert result.test_access.snapshot_id == SNAPSHOT_ID
        assert result.dataset.samples and count_test_accesses(registry, ALPHA, 1) == count
        assert all(s.label_end_time < result.window.end_us for s in result.dataset.samples)
    loader = MagicMock()
    with pytest.raises(BudgetExhausted):
        build_split_dataset(
            engine,
            experiment_id=experiment.experiment_id,
            alpha_id=ALPHA,
            version=1,
            split=Split.TEST,
            config=DatasetConfig(features=("momentum",)),
            load_inputs=loader,
            actor="test",
            purpose="Synthetic ML split verification",
        )
    loader.assert_not_called()
