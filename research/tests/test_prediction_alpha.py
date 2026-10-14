from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from test_common_types import lineage
from test_hourly_baselines import pair

from helios.common.config import config_hash
from helios.common.project_config import load_fees
from helios.common.types import AlphaStatus
from helios.ml.calibration import IsotonicMap
from helios.ml.dataset import HOUR_US, DatasetError
from helios.ml.prediction_alpha import (
    MLAlphaPolicy,
    TrainingPayoffs,
    fit_train_payoffs,
    prediction_to_alpha,
)


def fixture(ready=0):
    cal = IsotonicMap(
        x=(0.0, 1.0),
        y=(0.0, 1.0),
        available_after_us=ready,
        source_metrics_sha256="a" * 64,
        model_sha256="b" * 64,
        snapshot_id="fixture1",
    )
    payoffs = TrainingPayoffs(
        means_bps={"BTCUSDT": (100.0, -100.0)},
        counts={"BTCUSDT": (5, 5)},
        snapshot_id="fixture1",
        available_after_us=0,
    )
    policy = MLAlphaPolicy(calibration=cal, payoffs=payoffs, fees=load_fees(), window=3)
    ln = lineage().model_copy(
        update=dict(config_hash=config_hash(policy), snapshot_id="fixture1", model_hash="b" * 64)
    )
    frame = pd.DataFrame(
        dict(
            symbol=["BTCUSDT"] * 8,
            open_time=np.arange(8, dtype=np.int64) * HOUR_US,
            probability_positive=[0.1, 0.2, 0.8, 0.9, 0.5, 0.3, 0.8, 0.7],
        )
    )
    return policy, ln, frame


def test_signed_round_trip_cost_and_inside_cost_no_trade():
    policy, ln, frame = fixture()
    result = prediction_to_alpha(frame, policy, ln)
    rows = result.diagnostics
    assert rows.gross_edge_bps.iloc[0] == pytest.approx(-80)
    assert rows.net_edge_bps.iloc[0] == pytest.approx(-56)
    assert rows.net_edge_bps.iloc[2] == pytest.approx(36)
    assert rows.alpha.iloc[4] == 0
    assert all(-1 <= v.value <= 1 for v in result.values if v.status is AlphaStatus.OK)


@pytest.mark.leakage
def test_future_probabilities_cannot_change_earlier_values():
    policy, ln, frame = fixture()
    one = prediction_to_alpha(frame, policy, ln)
    frame.loc[5:, "probability_positive"] = [0.01, 0.99, 0.01]
    two = prediction_to_alpha(frame, policy, ln)
    assert one.values[:5] == two.values[:5]


@pytest.mark.leakage
def test_prefit_history_is_explicitly_unavailable():
    policy, ln, frame = fixture(ready=100 * HOUR_US)
    result = prediction_to_alpha(frame, policy, ln)
    assert result.diagnostics.diagnostic_alpha.notna().any()
    assert all(v.status is AlphaStatus.UNAVAILABLE and v.value is None for v in result.values)


def test_missing_intervals_and_probability_mask_reset_window():
    policy, ln, frame = fixture()
    frame = frame.drop(index=3).reset_index(drop=True)
    result = prediction_to_alpha(frame, policy, ln)
    assert result.values[3].value is None and result.values[4].value is None
    frame.loc[4, "probability_positive"] = np.nan
    assert prediction_to_alpha(frame, policy, ln).values[-1].value is None


@pytest.mark.leakage
def test_train_payoff_fit_refuses_valid_and_retains_class_counts():
    _, train, valid = pair()
    fitted = fit_train_payoffs(train)
    assert sum(fitted.counts["BTCUSDT"]) == len(train.dataset.samples)
    with pytest.raises(DatasetError, match="TRAIN only"):
        fit_train_payoffs(valid)
    changed = replace(train, dataset=replace(train.dataset, snapshot_id=None))
    with pytest.raises(DatasetError):
        fit_train_payoffs(changed)


def test_lineage_mismatch_and_duplicate_keys_rejected():
    policy, ln, frame = fixture()
    with pytest.raises(DatasetError, match="lineage"):
        prediction_to_alpha(frame, policy, ln.model_copy(update=dict(model_hash="c" * 64)))
    with pytest.raises(DatasetError, match="unique"):
        prediction_to_alpha(pd.concat([frame, frame.tail(1)]), policy, ln)
