"""Session formula causality and integration with unchanged replay accounting."""

from unittest.mock import patch

import pandas as pd
import pytest
from test_dashboard_nse_backtest import options
from test_equity_research import fixture_inputs

from helios.dashboard.lab_templates import TEMPLATES, expand, expression_signal
from helios.dashboard.nse_backtest import DatasetChoice, read_run, run_backtest
from helios.data.equities import sha256


@pytest.fixture
def session_source(tmp_path, monkeypatch):
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "manifest.json").write_text("{}")
    data = fixture_inputs(days=2)
    monkeypatch.setattr("helios.dashboard.nse_backtest.load_equity_inputs", lambda *args: data)
    monkeypatch.setattr("helios.dashboard.nse_backtest._sources", lambda destination: {})
    return DatasetChoice(snapshot, "1h", ("EXAMPLE",), sha256(snapshot / "manifest.json")), data


@pytest.mark.parametrize(
    "template,field,window,interval",
    [
        ('__import__("os")', "close", 1, "1h"),
        ("lag(close, -1)", "close", 1, "1h"),
        ("lag(close, 0)", "close", 1, "1h"),
        ("lag(close, 520)", "close", 1, "1h"),
        ("ts_backfill(close, 2)", "close", 2, "1h"),
        ("cs_rank(close)", "close", 2, "1h"),
        ("sign($unknown)", "close", 2, "1h"),
        ("sign($field)", "profit", 2, "1h"),
        ("sign($field)", "close", 520, "1m"),
        ("sign($field)", "close", 2, "1d"),
    ],
)
def test_unsupported_future_or_unavailable_bindings_refused(template, field, window, interval):
    with pytest.raises(ValueError):
        expand(template, field, window, interval)


def test_expression_is_prefix_causal_and_keeps_warmup_unavailable():
    frame = fixture_inputs(days=1).bars
    expression = expand(TEMPLATES["Momentum"], "close", 2, "1h")
    before = expression_signal(frame, expression, "1h")
    changed = frame.copy()
    changed.loc[4:, "close"] *= 1.2
    after = expression_signal(changed, expression, "1h")
    pd.testing.assert_series_equal(before.values.iloc[:4], after.values.iloc[:4])
    assert not before.available.iloc[:2].any()
    assert before.values[before.available].between(0, 1).all()
    pd.testing.assert_series_equal(before.open_time, frame.open_time)
    assert (frame.open_time % 3_600_000_000 != 0).all()  # observed NSE opening phase


def test_insufficient_history_is_not_fabricated_as_cash_performance():
    frame = fixture_inputs(days=1).bars.iloc[:2]
    with pytest.raises(ValueError, match="warmup"):
        expression_signal(frame, "lag(close, 4)", "1h")


def test_formula_momentum_matches_original_template_ledger(session_source, tmp_path):
    dataset, _ = session_source
    original = run_backtest(
        dataset, options(strategy="Trend following", lookback=1), output_root=tmp_path / "old"
    )
    formula = expand(TEMPLATES["Momentum"], "close", 1, "1h")
    custom = run_backtest(
        dataset,
        options(strategy="Trend following", lookback=1, expression=formula),
        output_root=tmp_path / "new",
    )
    _, a, _ = read_run(original)
    protocol, b, _ = read_run(custom)
    for multiplier in ("1", "2"):
        assert a["scenarios"][multiplier]["summary"] == b["scenarios"][multiplier]["summary"]
        assert a["scenarios"][multiplier]["daily"] == b["scenarios"][multiplier]["daily"]
    assert protocol["options"]["expression"] == formula and b["eligible"] is False


def test_invalid_formula_refused_before_input_access(session_source, tmp_path):
    dataset, _ = session_source
    with patch(
        "helios.dashboard.nse_backtest.load_equity_inputs", side_effect=AssertionError("read")
    ):
        with pytest.raises(ValueError):
            run_backtest(
                dataset, options(expression="lag(close,-1)"), output_root=tmp_path / "runs"
            )
    assert not (tmp_path / "runs").exists()
