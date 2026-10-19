"""Golden causal-decision checks; synthetic observations carry no market claims."""

import hashlib
import json
import runpy
from pathlib import Path

import numpy as np
import pandas as pd

from helios.equities.paper_signals import Setup, decisions

BUNDLE = Path(__file__).resolve().parents[2] / "docs/research/nse_intraday_20261019"


def test_published_evidence_matches_measured_bytes():
    manifest = json.loads((BUNDLE / "manifest.json").read_text())
    assert manifest["publication_is_not_a_reexecution"]
    for name, receipt in manifest["files"].items():
        assert hashlib.sha256((BUNDLE / name).read_bytes()).hexdigest() == receipt["sha256"]


def test_reusable_decisions_match_executed_research_helper():
    archived = runpy.run_path(str(BUNDLE / "nse_papers_train1/paper_signals.py.source"))
    rng = np.random.default_rng(20261019)
    for _ in range(25):
        frame = bars()
        close = 100 + np.cumsum(rng.normal(0, 0.2, 375))
        frame["close"] = close
        frame["high"] = np.maximum(100, close) + 0.1
        frame["low"] = np.minimum(100, close) - 0.1
        options = dict(
            previous_close=100.1,
            opening_rvol=1.5,
            atr14=2.0,
            noise14=np.full(375, 0.005),
            top20=True,
        )
        for name in ("closing_momentum", "orb_rvol", "noise_vwap"):
            assert decisions(name, frame, Setup(**options)) == archived["decisions"](
                name, frame, archived["Setup"](**options)
            )


def bars():
    return pd.DataFrame(
        dict(
            open=np.full(375, 100.0),
            high=np.full(375, 100.1),
            low=np.full(375, 99.9),
            close=np.full(375, 100.0),
            volume=np.full(375, 100),
        )
    )


def test_closing_uses_overnight_and_early_information_only():
    frame = bars()
    frame.loc[29, "close"] = 100.2
    setup = Setup(previous_close=100.1)
    assert decisions("closing_momentum", frame, setup) == (344, 373)
    frame.loc[30:, ["open", "high", "low", "close"]] = 1.0
    assert decisions("closing_momentum", frame, setup) == (344, 373)
    assert decisions("closing_momentum", frame, Setup(previous_close=101)) is None


def test_orb_confirms_completed_range_and_delays_execution():
    frame = bars()
    frame.loc[4, "close"] = 100.05
    frame.loc[9, "close"] = 100.2
    frame.loc[14, "close"] = 99.9
    setup = Setup(100, opening_rvol=2, atr14=2, top20=True)
    assert decisions("orb_rvol", frame, setup) == (9, 14)
    # Huge intrabar high alone cannot trigger an assumed stop-order execution.
    frame.loc[9, "close"] = 100.0
    frame.loc[9, "high"] = 110
    assert decisions("orb_rvol", frame, setup) is None


def test_orb_rvol_filter_and_no_reentry():
    frame = bars()
    frame.loc[4, "close"] = 100.05
    frame.loc[9, "close"] = 100.2
    frame.loc[14, "close"] = 99.9
    frame.loc[19, "close"] = 110
    assert decisions("orb_rvol", frame, Setup(100, opening_rvol=2, atr14=2, top20=True)) == (9, 14)
    assert decisions("orb_rvol", frame, Setup(100, opening_rvol=0.99, atr14=2, top20=True)) is None
    assert decisions("orb_rvol", frame, Setup(100, opening_rvol=2, atr14=2, top20=False)) is None


def test_noise_decision_grid_and_causal_exit():
    frame = bars()
    frame.loc[29, "close"] = 101
    setup = Setup(100, noise14=np.full(375, 0.005))
    assert decisions("noise_vwap", frame, setup) == (29, 59)
    frame.loc[60:, ["high", "low", "close", "volume"]] = 999
    assert decisions("noise_vwap", frame, setup) == (29, 59)
    frame = bars()
    frame.loc[30, "close"] = 105
    assert decisions("noise_vwap", frame, setup) is None


def test_final_known_exit_and_entry_cutoff():
    frame = bars()
    frame.loc[:, "close"] = 102
    setup = Setup(100, noise14=np.full(375, 0.005))
    assert decisions("noise_vwap", frame, setup) == (29, 373)
    frame = bars()
    frame.loc[359:, "close"] = 102
    assert decisions("noise_vwap", frame, setup) is None
