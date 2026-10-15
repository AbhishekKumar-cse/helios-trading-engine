import numpy as np
import pytest
from test_calibration import predictions
from test_registered_ml_alpha import artifact_fixture

from helios.common.project_config import HorizonFamily
from helios.ml.calibration import fit_valid_calibration
from helios.ml.dataset import DatasetError
from helios.ml.minute_pipeline import minute_ml_protocol
from helios.ml.registered_alpha import frozen_definition, frozen_ml_series, read_frozen_ml
from helios.registry.results import Split
from helios.sim.splits import split_window


@pytest.mark.leakage
def test_minute_calibration_grid_and_availability():
    frame = predictions()
    window = split_window(Split.VALID, interval="1m")
    frame.open_time = window.start_us + np.arange(len(frame), dtype=np.int64) * 60_000_000
    frame.label_end_time = frame.open_time + 60_000_000
    frozen, _, _ = fit_valid_calibration(
        frame, window, source_metrics_sha256="a" * 64, model_sha256="b" * 64, snapshot_id="fixture1"
    )
    assert frozen.available_after_us == window.end_us
    with pytest.raises(DatasetError, match="boundary"):
        fit_valid_calibration(
            frame,
            split_window(Split.VALID, interval="1h"),
            source_metrics_sha256="a" * 64,
            model_sha256="b" * 64,
            snapshot_id="fixture1",
        )


@pytest.mark.leakage
def test_frozen_minute_signals_use_minute_grid_and_remain_unavailable(tmp_path):
    artifact = read_frozen_ml(artifact_fixture(tmp_path, interval="1m"))
    definition = frozen_definition(artifact)
    assert definition.horizon_family is HorizonFamily.MINUTE
    series, evidence = frozen_ml_series(
        definition,
        split_window(Split.VALID, interval="1m"),
        symbol="BTCUSDT",
        snapshot_id=artifact.policy.calibration.snapshot_id,
    )
    assert len(series.values) == 7 and not series.available.any()
    assert series.open_time.iloc[0] == artifact.values[0].timestamp - 60_000_000
    assert evidence["available_rows"] == 0
    with pytest.raises(DatasetError, match="match"):
        frozen_ml_series(
            definition,
            split_window(Split.VALID, interval="1h"),
            symbol="BTCUSDT",
            snapshot_id=artifact.policy.calibration.snapshot_id,
        )


def test_fixed_protocol_has_no_test_or_search():
    protocol = minute_ml_protocol()
    assert protocol["config"]["dataset"]["interval"] == "1m"
    assert protocol["config"]["symbols"] == ["BTCUSDT"]
    assert protocol["config"]["seed"] == 0
    assert protocol["test_access"] is protocol["tune"] is False
