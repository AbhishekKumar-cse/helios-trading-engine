"""Development-boundary, accounting, causality, integrity and button regressions."""

from dataclasses import replace
from datetime import date
from decimal import Decimal, localcontext
from unittest.mock import patch

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest
from test_equity_minutes import minute_fixture
from test_equity_research import fixture_inputs

from helios.dashboard.nse_backtest import (
    DatasetChoice,
    NseOptions,
    read_run,
    run_backtest,
    template_signal,
)
from helios.data.equities import sha256


def options(**changes):
    return NseOptions(
        **(
            dict(
                symbol="EXAMPLE",
                start=date(2026, 1, 9),
                end=date(2026, 1, 12),
                strategy="Long during session",
                lookback=1,
            )
            | changes
        )
    )


@pytest.fixture
def source(tmp_path, monkeypatch):
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "manifest.json").write_text("{}")
    data = fixture_inputs(days=2)
    monkeypatch.setattr("helios.dashboard.nse_backtest.load_equity_inputs", lambda *args: data)
    monkeypatch.setattr("helios.dashboard.nse_backtest._sources", lambda destination: {})
    return DatasetChoice(snapshot, "1h", ("EXAMPLE",), sha256(snapshot / "manifest.json")), data


@pytest.mark.parametrize(
    "changes",
    [
        dict(start=date(2025, 12, 31)),
        dict(end=date(2026, 7, 1)),
        dict(end=date(2026, 2, 20)),
        dict(start=date(2026, 1, 13), end=date(2026, 1, 9)),
    ],
)
def test_test_dates_and_oversized_windows_rejected_before_any_load(source, tmp_path, changes):
    dataset, _ = source
    unsafe = options().model_copy(update=changes)
    with patch(
        "helios.dashboard.nse_backtest.load_equity_inputs", side_effect=AssertionError("read")
    ):
        with pytest.raises(ValueError):
            run_backtest(dataset, unsafe, output_root=tmp_path / "runs")
    assert not (tmp_path / "runs").exists()


def test_signal_prefix_unchanged_by_future_prices_and_session_reset():
    data = fixture_inputs(days=1).bars
    before = template_signal(data, "Trend following", 2)
    changed = data.copy()
    changed.loc[4:, "close"] *= 1.2
    after = template_signal(changed, "Trend following", 2)
    pd.testing.assert_series_equal(before.values.iloc[:4], after.values.iloc[:4])
    assert not before.available.iloc[:2].any()
    with pytest.raises(ValueError, match="one chronological"):
        template_signal(fixture_inputs(days=2).bars, "Trend following", 2)


def test_actual_shared_accounts_carry_cash_reconcile_fees_and_preserve_artifacts(source, tmp_path):
    dataset, _ = source
    directory = run_backtest(dataset, options(), output_root=tmp_path / "runs")
    protocol, result, bars = read_run(directory)
    assert len(bars) == 14 and protocol["registry_writes"] == protocol["test_accesses"] == 0
    assert not result["eligible"] and set(result["scenarios"]) == {"1", "2"}
    for run in result["scenarios"].values():
        assert run["daily"][1]["start_cash"] == run["daily"][0]["end_cash"]
        assert all(d["terminal_inventory"] == 0 for d in run["daily"])
        with localcontext() as ctx:
            ctx.prec = 100
            cash = Decimal(100000)
            for fill in sorted(run["fills"], key=lambda x: x["timestamp"]):
                value = Decimal(fill["quantity"]) * Decimal(fill["price"])
                cash += (-value if fill["side"] == "BUY" else value) - Decimal(fill["fee"])
                assert Decimal(fill["quantity"]) == Decimal(fill["quantity"]).to_integral_value()
            cash -= sum(Decimal(x["amount"]) for x in run["fee_adjustments"])
            assert cash == Decimal(run["summary"]["final_equity"])
    old = (directory / "result.json").read_bytes()
    second = run_backtest(dataset, options(), output_root=tmp_path / "runs")
    assert second != directory and (directory / "result.json").read_bytes() == old
    (directory / "observations.parquet").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="checksum"):
        read_run(directory)


def test_missing_session_is_reported_without_zero_return_or_backfill(source, tmp_path, monkeypatch):
    dataset, data = source
    broken = replace(data, bars=data.bars.drop(index=0).reset_index(drop=True))
    monkeypatch.setattr("helios.dashboard.nse_backtest.load_equity_inputs", lambda *args: broken)
    directory = run_backtest(dataset, options(), output_root=tmp_path / "runs")
    protocol, result, _ = read_run(directory)
    assert len(protocol["expected_sessions"]) == 2 and len(protocol["excluded_sessions"]) == 1
    assert len(result["scenarios"]["1"]["daily"]) == 1
    assert result["scenarios"]["1"]["daily"][0]["day"] == "2026-01-12"


def test_minute_reference_charges_are_in_total_cash_fees(source, tmp_path, monkeypatch):
    dataset, data = source
    frame = minute_fixture()
    frame["session_slots"], frame["session_open_minute"] = 375, 555
    data = replace(data, bars=frame, expected_sessions=("2026-01-09",))
    monkeypatch.setattr("helios.dashboard.nse_backtest.load_equity_inputs", lambda *args: data)
    dataset = replace(dataset, interval="1m")
    directory = run_backtest(dataset, options(end=date(2026, 1, 9)), output_root=tmp_path / "runs")
    _, result, _ = read_run(directory)
    normal = result["scenarios"]["1"]
    assert normal["fee_adjustments"] and Decimal(normal["summary"]["fees"]) > 0
    charged = sum(Decimal(f["fee"]) for f in normal["fills"]) + sum(
        Decimal(x["amount"]) for x in normal["fee_adjustments"]
    )
    assert charged == Decimal(normal["summary"]["fees"])


def test_quarantine_and_changed_manifest_are_refused(source, tmp_path):
    dataset, _ = source
    bad = replace(dataset, symbols=("BSE",))
    with pytest.raises(ValueError, match="quarantined"):
        run_backtest(bad, options(symbol="BSE"), output_root=tmp_path / "runs")
    (dataset.path / "manifest.json").write_text('{"changed":true}')
    with pytest.raises(ValueError, match="manifest changed"):
        run_backtest(dataset, options(), output_root=tmp_path / "runs")


def test_controls_never_run_automatically_and_old_result_is_labelled(source, tmp_path):
    dataset, _ = source
    directory = run_backtest(dataset, options(), output_root=tmp_path / "runs")
    with (
        patch("helios.dashboard.nse_backtest_page.datasets", return_value=[dataset]),
        patch("helios.dashboard.nse_backtest_page.run_backtest", return_value=directory) as runner,
    ):
        app = AppTest.from_string(
            "from helios.dashboard.nse_backtest_page import render_nse_backtest\n"
            "render_nse_backtest()",
            default_timeout=30,
        )
        app.run()
        assert not app.exception and not runner.called
        next(b for b in app.button if b.label == "Run NSE backtest").click().run()
        assert not app.exception and runner.call_count == 1 and len(app.metric) == 5
        app.number_input[0].set_value(200000).run()
        assert not app.exception and runner.call_count == 1
        assert any("Settings changed" in x.value for x in app.info)
        assert any(b.label == "Download NSE backtest" for b in app.get("download_button"))
        next(b for b in app.button if b.label == "Reset replay").click().run()
        assert not app.exception and app.session_state.nse_cursor == 0
        assert app.metric[3].value == "0" and runner.call_count == 1
        assert not any(b.label == "Download NSE backtest" for b in app.get("download_button"))
        next(b for b in app.button if b.label == "Next bar").click().run()
        assert not app.exception and app.session_state.nse_cursor == 1
        next(b for b in app.button if b.label == "Play replay").click().run()
        assert not app.exception and app.session_state.nse_playing
        next(b for b in app.button if b.label == "Pause").click().run()
        assert not app.exception and not app.session_state.nse_playing
        assert runner.call_count == 1  # playback must not rerun the execution backend
