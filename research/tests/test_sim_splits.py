"""Split boundaries, isolated accounting and pre-load TEST reservations."""

from contextlib import contextmanager
from dataclasses import replace
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import Connection, Engine
from test_sim_costs import gross
from test_sim_positions import HOUR, inputs, table
from test_test_access import ALPHA, SNAPSHOT_ID
from test_test_access import registry as _registry_fixture

from helios.common.project_config import HorizonFamily, load_splits
from helios.registry.experiments import register_experiment
from helios.registry.results import Split
from helios.registry.test_access import TestSetLimitReached as BudgetExhausted
from helios.registry.test_access import count_test_accesses
from helios.sim.costs import apply_costs
from helios.sim.positions import SimulationError
from helios.sim.splits import _authorize, _split_inputs, evaluate_split, split_window
from helios.sim.validity import ValidityConfig

registry = pytest.fixture(_registry_fixture.__wrapped__)


@pytest.mark.parametrize(
    "interval,family,gap", [("1h", HorizonFamily.HOURLY, 7), ("1m", HorizonFamily.MINUTE, 1)]
)
def test_exact_inclusive_dates_exclusive_bounds_and_embargo(interval, family, gap) -> None:
    config = load_splits()
    windows = [split_window(s, interval=interval) for s in Split]
    assert all(w.family == family and len(w.splits_hash) == 64 for w in windows)
    assert windows[1].start_us - windows[0].end_us == gap * 24 * HOUR
    assert windows[2].start_us - windows[1].end_us == gap * 24 * HOUR
    assert pd.to_datetime(windows[0].end_us, unit="us", utc=True).date() == config.families[
        family
    ].train.end + pd.Timedelta(days=1)
    with pytest.raises(SimulationError, match="embargo"):
        split_window(
            Split.VALID,
            interval=interval,
            horizon_periods=gap * 24 * (1 if interval == "1h" else 60) + 1,
        )


def split_data(window, constant=False):
    values = [1, -1, 0.5, 0, 1] if not constant else [1] * 5
    return inputs(values=values, times=[window.start_us + i * HOUR for i in range(5)])


def test_prior_history_excluded_and_future_rows_refused() -> None:
    window = split_window(Split.VALID, interval="1h")
    alpha, bars = inputs(times=[window.start_us - HOUR + i * HOUR for i in range(5)])
    selected, selected_bars = _split_inputs(alpha, bars, window)
    assert len(selected.values) == len(selected_bars) == 4
    assert selected.open_time.iloc[0] == window.start_us
    future = replace(window, end_us=window.start_us + HOUR)
    with pytest.raises(SimulationError, match="authorized"):
        _split_inputs(alpha, bars, future)
    missing = replace(
        alpha,
        open_time=alpha.open_time.iloc[[0, 1, 3, 4]],
        values=alpha.values.iloc[[0, 1, 3, 4]],
        available=alpha.available.iloc[[0, 1, 3, 4]],
    )
    aligned, _ = _split_inputs(missing, bars, window)
    assert not aligned.available.iloc[1] and np.isnan(aligned.values.iloc[1])


def test_metrics_are_separate_and_warmup_never_earns_pnl() -> None:
    engine = MagicMock(spec=Engine)

    def simulate(connection, *, alpha, bars, **kwargs):
        return apply_costs(replace(gross(), table=table(alpha, bars)))

    with (
        patch("helios.sim.splits._authorize", return_value=None),
        patch("helios.sim.splits.simulate_net", side_effect=simulate),
    ):
        results = [
            evaluate_split(
                engine,
                experiment_id=1,
                alpha_id="example",
                version=1,
                split=s,
                interval="1h",
                load_inputs=split_data,
                validity_config=ValidityConfig(warmup_rows=1),
            )
            for s in (Split.TRAIN, Split.VALID)
        ]
    for result in results:
        assert result.validity.valid and result.diagnostics.base.metrics.n_periods == 3
        assert result.simulation.table.open_time.iloc[0] == result.window.start_us + HOUR
        assert result.simulation.table.initial_boundary.iloc[0]
        assert result.simulation.table.held_position.iloc[0] == 0
        assert result.test_access is None
    assert results[0].window.split != results[1].window.split


def test_invalid_input_returns_no_performance_metrics() -> None:
    engine = MagicMock(spec=Engine)
    with (
        patch("helios.sim.splits._authorize", return_value=None),
        patch("helios.sim.splits.simulate_net") as simulator,
    ):
        result = evaluate_split(
            engine,
            experiment_id=1,
            alpha_id="example",
            version=1,
            split=Split.VALID,
            interval="1h",
            load_inputs=lambda w: split_data(w, True),
        )
    assert not result.validity.valid and result.diagnostics is result.simulation is None
    simulator.assert_not_called()


def test_reservation_commits_before_loader_even_if_loader_fails() -> None:
    events = []

    class TransactionEngine:
        @contextmanager
        def begin(self):
            yield MagicMock()
            events.append("commit")

    def load(window):
        events.append("load")
        raise RuntimeError("loader failed after authorization")

    def authorize(*args, **kwargs):
        events.append("reserve")

    with patch("helios.sim.splits._authorize", side_effect=authorize):
        with pytest.raises(RuntimeError, match="loader failed"):
            evaluate_split(
                TransactionEngine(),
                experiment_id=1,
                alpha_id="example",
                version=1,
                split=Split.TEST,
                interval="1h",
                load_inputs=load,
            )
    assert events == ["reserve", "commit", "load"]
    loader = MagicMock()
    with patch("helios.sim.splits._authorize", side_effect=BudgetExhausted("budget exhausted")):
        with pytest.raises(BudgetExhausted):
            evaluate_split(
                TransactionEngine(),
                experiment_id=1,
                alpha_id="example",
                version=1,
                split=Split.TEST,
                interval="1h",
                load_inputs=loader,
            )
    loader.assert_not_called()


def test_real_database_reservations_two_allowed_third_refused(registry: Connection) -> None:
    experiment = register_experiment(
        registry,
        hypothesis="Synthetic guarded split verification",
        author="test",
        snapshot_id=SNAPSHOT_ID,
    )
    window = split_window(Split.TEST, interval="1h")
    for expected in (1, 2):
        access = _authorize(
            registry,
            window,
            experiment_id=experiment.experiment_id,
            alpha_id=ALPHA,
            version=1,
            actor="test",
            purpose="Synthetic final confirmation",
        )
        assert (
            access.snapshot_id == SNAPSHOT_ID
            and count_test_accesses(registry, ALPHA, 1) == expected
        )
    with pytest.raises(BudgetExhausted):
        _authorize(
            registry,
            window,
            experiment_id=experiment.experiment_id,
            alpha_id=ALPHA,
            version=1,
            actor="test",
            purpose="Synthetic final confirmation",
        )
    assert (
        _authorize(
            registry,
            split_window(Split.VALID, interval="1h"),
            experiment_id=experiment.experiment_id,
            alpha_id=ALPHA,
            version=1,
            actor="",
            purpose="",
        )
        is None
    )
    assert count_test_accesses(registry, ALPHA, 1) == 2


def test_registered_horizon_and_snapshot_required(registry: Connection) -> None:
    experiment = register_experiment(
        registry, hypothesis="Synthetic authorization validation", author="test"
    )
    with pytest.raises(SimulationError, match="horizon"):
        _authorize(
            registry,
            split_window(Split.VALID, interval="1m"),
            experiment_id=experiment.experiment_id,
            alpha_id=ALPHA,
            version=1,
            actor="test",
            purpose="Synthetic verification",
        )
    with pytest.raises(Exception, match="snapshot"):
        _authorize(
            registry,
            split_window(Split.TEST, interval="1h"),
            experiment_id=experiment.experiment_id,
            alpha_id=ALPHA,
            version=1,
            actor="test",
            purpose="Synthetic verification",
        )
