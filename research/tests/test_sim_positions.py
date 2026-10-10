"""Hand-calculated causal execution, exact alignment and real preregistration checks."""

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError
from sqlalchemy import Connection

from helios.alpha.evaluator import AlphaSeries
from helios.alpha.output import BoundedAlphaSeries, OutputConvention, bound_alpha
from helios.registry.api import RegistryError
from helios.registry.experiments import ExperimentStatus, register_experiment, set_status
from helios.sim.positions import PositionConfig, SimulationError, _position_table, simulate_gross

HOUR = 3_600_000_000


def inputs(
    values: list[float] | None = None,
    prices: list[float] | None = None,
    times: list[int] | None = None,
    scale: float = 1.0,
) -> tuple[BoundedAlphaSeries, pd.DataFrame]:
    values = [1.0, -1.0, 0.5, 0.0, 1.0] if values is None else values
    prices = [100.0, 110.0, 99.0, 99.0, 108.9] if prices is None else prices
    times = [i * HOUR for i in range(len(values))] if times is None else times
    index = pd.Index(range(100, 100 + len(values)))
    raw = AlphaSeries(
        "BTCUSDT",
        pd.Series(times, index=index),
        pd.Series(values, index=index),
        pd.Series(True, index=index),
    )
    alpha = bound_alpha(raw, output=OutputConvention(position_scale=scale))
    bars = pd.DataFrame(
        {"open_time": times, "close": prices}, index=range(1000, 1000 + len(prices))
    )
    return alpha, bars


def table(alpha: BoundedAlphaSeries, bars: pd.DataFrame, *, lag: int = 1) -> pd.DataFrame:
    return _position_table(
        alpha,
        bars,
        PositionConfig(
            interval="1h", execution_lag=lag, position_scale=alpha.output.position_scale
        ),
    )


def test_five_bar_golden_uses_previous_position_and_turnover() -> None:
    alpha, bars = inputs()
    result = table(alpha, bars)
    np.testing.assert_allclose(
        result.period_return, [np.nan, 0.1, -0.1, 0, 0.1], atol=1e-14, equal_nan=True
    )
    np.testing.assert_allclose(result.gross_return, [0, 0.1, 0.1, 0, 0], atol=1e-14, equal_nan=True)
    np.testing.assert_allclose(result.turnover, [1, 2, 1.5, 0.5, 1])
    assert result.gross_available.tolist() == [True, True, True, True, True]
    assert result.initial_boundary.tolist() == [True, False, False, False, False]
    assert not result.return_available.iloc[0] and np.isnan(result.period_return.iloc[0])
    assert result.index.equals(bars.index)
    assert result.open_time.tolist() == alpha.open_time.tolist()


def test_scale_mapping_clips_without_dividing_alpha_twice() -> None:
    alpha, bars = inputs(scale=0.25)
    result = table(alpha, bars)
    np.testing.assert_array_equal(result.target_position, [1.0, -1.0, 1.0, 0.0, 1.0])
    alpha, bars = inputs(scale=2)
    np.testing.assert_array_equal(table(alpha, bars).position, [0.5, -0.5, 0.25, 0, 0.5])


def test_two_interval_execution_waits_flat_then_charges_initial_entry() -> None:
    alpha, bars = inputs()
    result = table(alpha, bars, lag=2)
    np.testing.assert_allclose(result.position, [0, 1, -1, 0.5, 0])
    np.testing.assert_allclose(
        result.gross_return, [0, 0, -0.1, 0, 0.05], atol=1e-14, equal_nan=True
    )
    np.testing.assert_array_equal(result.turnover, [0, 1, 2, 1.5, 0.5])


def test_long_execution_lag_stays_declared_flat_without_allocating_lag_history() -> None:
    alpha, bars = inputs()
    result = table(alpha, bars, lag=2**62)
    assert (result.position == 0).all() and (result.turnover == 0).all()
    assert result.gross_return.iloc[1:].eq(0).all()


def test_startup_warmup_stays_flat_then_records_first_entry() -> None:
    alpha, bars = inputs(values=[np.nan, np.nan, 1.0, -1.0, 0.0])
    result = table(alpha, bars)
    np.testing.assert_array_equal(result.position, [0, 0, 1, -1, 0])
    np.testing.assert_array_equal(result.turnover, [0, 0, 1, 2, 1])
    assert not result.alpha_available.iloc[:2].any()
    assert result.gross_return.iloc[:3].eq(0).all()


def test_single_bar_is_only_accounting_boundary_without_fabricated_exit() -> None:
    alpha, bars = inputs(values=[1.0], prices=[100.0])
    result = table(alpha, bars)
    assert len(result) == 1 and result.initial_boundary.iloc[0]
    assert np.isnan(result.period_return.iloc[0]) and not result.return_available.iloc[0]
    assert result.gross_return.iloc[0] == 0 and result.turnover.iloc[0] == 1


def test_missing_current_alpha_does_not_poison_previous_held_return() -> None:
    alpha, bars = inputs(values=[1.0, np.nan, -1.0, 0.5, 0.0])
    result = table(alpha, bars)
    assert result.gross_available.iloc[1]  # prior signal still earns this interval
    assert not result.gross_available.iloc[2]
    assert not result.turnover_available.iloc[1:3].any()
    assert result.gross_available.iloc[3]


def test_missing_alpha_row_aligns_exact_time_without_filling() -> None:
    alpha, bars = inputs()
    alpha = BoundedAlphaSeries(
        alpha.symbol,
        alpha.open_time.drop(101),
        alpha.values.drop(101),
        alpha.available.drop(101),
        alpha.output,
    )
    result = table(alpha, bars)
    assert not result.alpha_available.iloc[1]
    assert result.gross_available.iloc[1] and not result.gross_available.iloc[2]
    assert result.position.iloc[2] == 0.5


def test_gap_cannot_be_treated_as_one_interval() -> None:
    alpha, bars = inputs(times=[0, HOUR, 3 * HOUR, 4 * HOUR, 5 * HOUR])
    result = table(alpha, bars)
    assert np.isnan(result.period_return.iloc[2])
    assert not result.gross_available.iloc[2] and not result.turnover_available.iloc[2]
    assert result.gross_available.iloc[3]
    delayed = table(alpha, bars, lag=2)
    assert not delayed.position_available.iloc[2]


@pytest.mark.parametrize("missing", [np.nan, np.inf])
def test_unknown_close_masks_both_adjacent_returns(missing: float) -> None:
    alpha, bars = inputs(prices=[100.0, 110.0, missing, 99.0, 108.9])
    result = table(alpha, bars)
    assert not result.gross_available.iloc[2:4].any()
    assert result.gross_available.iloc[4]


@pytest.mark.parametrize("lag", [0, -1, True, 1.5, 2**63])
def test_noncausal_or_invalid_lag_rejected(lag: object) -> None:
    with pytest.raises(ValidationError):
        PositionConfig.model_validate(
            {"interval": "1h", "execution_lag": lag, "position_scale": 1.0}
        )


@pytest.mark.parametrize(
    "defect",
    [
        "duplicate",
        "reversed",
        "off_grid",
        "zero_close",
        "boolean_close",
        "mixed_symbol",
        "extra_alpha",
        "uint_wrap",
    ],
)
def test_bad_alignment_and_price_inputs_rejected(defect: str) -> None:
    alpha, bars = inputs()
    if defect == "duplicate":
        bars.iloc[1, 0] = 0
    elif defect == "reversed":
        bars = bars.iloc[::-1]
    elif defect == "off_grid":
        bars.iloc[1, 0] += 1
    elif defect == "zero_close":
        bars.iloc[1, 1] = 0
    elif defect == "boolean_close":
        bars["close"] = True
    elif defect == "mixed_symbol":
        bars["symbol"] = ["BTCUSDT"] * 4 + ["ETHUSDT"]
    elif defect == "extra_alpha":
        bars = bars.iloc[:-1]
    else:
        bars["open_time"] = pd.Series(
            [2**63 + i * HOUR for i in range(5)], index=bars.index, dtype="uint64"
        )
    with pytest.raises(SimulationError):
        table(alpha, bars)


def test_inputs_and_output_do_not_share_mutable_data() -> None:
    alpha, bars = inputs()
    before = bars.copy(deep=True)
    result = table(alpha, bars)
    result.iloc[0, 0] = 999
    pd.testing.assert_frame_equal(bars, before)
    assert alpha.open_time.iloc[0] == 0


@given(
    st.floats(min_value=-1, max_value=1, allow_nan=False),
    st.floats(min_value=1, max_value=10000, allow_nan=False),
)
@settings(max_examples=25, deadline=None)
def test_future_signal_price_changes_and_truncation_do_not_rewrite_past(
    value: float,
    price: float,
) -> None:
    alpha, bars = inputs()
    expected = table(alpha, bars).iloc[:-1]
    alpha.values.iloc[-1] = value
    bars.iloc[-1, 1] = price
    pd.testing.assert_frame_equal(expected, table(alpha, bars).iloc[:-1])
    short = BoundedAlphaSeries(
        alpha.symbol,
        alpha.open_time.iloc[:-1],
        alpha.values.iloc[:-1],
        alpha.available.iloc[:-1],
        alpha.output,
    )
    pd.testing.assert_frame_equal(expected, table(short, bars.iloc[:-1]))


def test_public_simulator_checks_experiment_before_computing(connection: Connection) -> None:
    alpha, bars = inputs()
    with patch("helios.sim.positions._position_table") as calculate:
        with pytest.raises(RegistryError, match="not registered"):
            simulate_gross(connection, experiment_id=2**62, alpha=alpha, bars=bars, interval="1h")
        calculate.assert_not_called()


def test_public_simulator_uses_registered_experiment_and_stored_scale(
    connection: Connection,
) -> None:
    experiment = register_experiment(
        connection,
        hypothesis="Synthetic timing should match by hand",
        params={"execution_lag": 1},
        author="test",
    )
    alpha, bars = inputs(scale=2.0)
    result = simulate_gross(
        connection, experiment_id=experiment.experiment_id, alpha=alpha, bars=bars, interval="1h"
    )
    assert result.experiment_id == experiment.experiment_id
    assert result.config.position_scale == 2
    assert len(result.config_hash) == 64 and len(result.code_commit) == 40
    assert result.snapshot_id is None  # synthetic test has no invented market snapshot
    set_status(connection, experiment.experiment_id, ExperimentStatus.RUNNING)
    set_status(connection, experiment.experiment_id, ExperimentStatus.FINISHED)
    with pytest.raises(RegistryError):
        simulate_gross(
            connection,
            experiment_id=experiment.experiment_id,
            alpha=alpha,
            bars=bars,
            interval="1h",
        )
