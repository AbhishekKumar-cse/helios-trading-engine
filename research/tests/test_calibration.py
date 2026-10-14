import numpy as np
import pandas as pd
import pytest

from helios.ml.calibration import fit_valid_calibration
from helios.ml.dataset import HOUR_US, DatasetError
from helios.registry.results import Split
from helios.sim.splits import split_window


def predictions():
    window = split_window(Split.VALID, interval="1h")
    times = window.start_us + np.arange(10, dtype=np.int64) * HOUR_US
    return pd.DataFrame(
        dict(
            symbol=["BTCUSDT"] * 10,
            open_time=times,
            label_end_time=times + HOUR_US,
            target=[-0.01, 0.01] * 5,
            direction_label=[0, 1] * 5,
            probability_positive=np.linspace(0.1, 0.9, 10),
        )
    )


def fit(frame=None, split=Split.VALID):
    return fit_valid_calibration(
        predictions() if frame is None else frame,
        split_window(split, interval="1h"),
        source_metrics_sha256="a" * 64,
        model_sha256="b" * 64,
        snapshot_id="fixture1",
    )


@pytest.mark.leakage
@pytest.mark.parametrize("split", [Split.TRAIN, Split.TEST])
def test_fit_never_accepts_train_or_test(split):
    with pytest.raises(DatasetError, match="VALID only"):
        fit(split=split)


def test_frozen_map_recomputes_and_extrapolates_with_explicit_readiness():
    frozen, output, report = fit()
    assert np.all(np.diff(output.probability_calibrated) >= 0)
    assert report["n_samples"] == sum(p["n"] for p in report["raw"]["curve"])
    np.testing.assert_array_equal(
        frozen.probabilities(output.probability_positive), output.probability_calibrated
    )
    assert frozen.available_after_us == split_window(Split.VALID, interval="1h").end_us
    assert frozen.probabilities(pd.Series([0.0, 1.0])).tolist() == [frozen.y[0], frozen.y[-1]]


@pytest.mark.parametrize("kind", ["probability", "label", "boundary", "duplicate", "shuffle"])
def test_malformed_rows_are_rejected(kind):
    frame = predictions()
    if kind == "probability":
        frame.loc[0, "probability_positive"] = np.nan
    elif kind == "label":
        frame.loc[0, "direction_label"] = 1
    elif kind == "boundary":
        frame.loc[9, "label_end_time"] = split_window(Split.VALID, interval="1h").end_us
    elif kind == "duplicate":
        frame = pd.concat([frame, frame.tail(1)])
    else:
        frame = frame.iloc[::-1]
    with pytest.raises(DatasetError):
        fit(frame)


def test_equal_times_across_symbols_are_valid():
    frame = pd.concat([predictions(), predictions().assign(symbol="ETHUSDT")])
    frame = frame.sort_values(["open_time", "symbol"]).reset_index(drop=True)
    assert fit(frame)[2]["n_samples"] == 20
