"""NSE runner preflight and retained access-denial failure, using test doubles."""

import json
import time
import urllib.error
from datetime import UTC, datetime
from itertools import count
from unittest.mock import MagicMock

import pandas as pd
import pytest
from sqlalchemy import Engine
from test_equity_paper import runtime
from test_loss_risk import Store

from helios.common.config import config_hash
from helios.common.lineage import RunContext
from helios.equities import paper_runner
from helios.equities.live import EquityClosedCandle


def setup_runner(tmp_path, monkeypatch):
    calendar = tmp_path / "calendar.json"
    calendar.write_text("{}")
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "manifest.json").write_text(
        json.dumps(dict(files=[dict(symbol="RELIANCE", isin="INE002A01018")]))
    )
    monkeypatch.setattr(paper_runner, "git_is_dirty", lambda: False)
    monkeypatch.setattr(paper_runner, "git_commit", lambda: "b" * 40)
    monkeypatch.setattr(paper_runner, "session_is_open", lambda *a: True)
    monkeypatch.setattr(
        paper_runner,
        "registered_definition",
        lambda *a: runtime().definition.model_copy(
            update={"alpha_id": "nse_minute_round1_momentum"}
        ),
    )
    monkeypatch.setattr(paper_runner, "PostgresTripStore", lambda *a: Store())
    monkeypatch.setattr(
        paper_runner.RunContext,
        "capture",
        lambda config, stream, seed, **kw: RunContext(
            "b" * 40, False, config_hash(config), stream, seed, datetime.now(UTC)
        ),
    )
    store = MagicMock(experiment_id=123)
    monkeypatch.setattr(paper_runner, "PaperStore", lambda *a: store)
    engine = MagicMock(spec=Engine)
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.mappings.return_value.one.return_value = dict(
        venue="nse_cash", quote_asset="INR", lot_size=1, tick_size=".05"
    )
    return calendar, snapshot, engine, store


def test_paper_runner_refuses_dirty_source_before_creating_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(paper_runner, "git_is_dirty", lambda: True)
    with pytest.raises(ValueError, match="clean source"):
        paper_runner.run_equity_paper("fixture", tmp_path / "absent")


def test_paper_runner_refuses_cross_instrument_candles(tmp_path, monkeypatch):
    calendar, snapshot, engine, _ = setup_runner(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="symbol/ISIN"):
        paper_runner.run_equity_paper(
            "fixture", calendar, isin="INE00000000X", snapshot=snapshot, engine=engine
        )
    engine.connect.assert_not_called()


def test_public_access_denial_is_terminal_and_retained(tmp_path, monkeypatch):
    calendar, snapshot, engine, store = setup_runner(tmp_path, monkeypatch)

    def denied(*args):
        raise urllib.error.HTTPError("https://example.invalid", 403, "denied", {}, None)

    monkeypatch.setattr(paper_runner, "public_get", denied)
    with pytest.raises(urllib.error.HTTPError):
        paper_runner.run_equity_paper(
            "fixture", calendar, root=tmp_path / "runs", snapshot=snapshot, engine=engine
        )
    artifact = json.loads((tmp_path / "runs/fixture/artifact.json").read_text())
    assert artifact["status"] == "FAILED" and artifact["error_type"] == "HTTPError"
    assert artifact["trace"]["orders"] == []
    store.finish.assert_called_once()
    assert store.finish.call_args.kwargs["failed"]


@pytest.mark.parametrize("seconds", [float("nan"), float("inf"), 0, 86401])
def test_runner_rejects_unbounded_or_invalid_duration(tmp_path, monkeypatch, seconds):
    calendar, snapshot, engine, _ = setup_runner(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="duration"):
        paper_runner.run_equity_paper(
            "fixture", calendar, seconds=seconds, snapshot=snapshot, engine=engine
        )
    engine.connect.assert_not_called()


def test_runner_waits_for_fresh_startup_bar_without_retiming_old_prices(tmp_path, monkeypatch):
    calendar, snapshot, engine, _ = setup_runner(tmp_path, monkeypatch)
    opened = time.time_ns() // 1000 - 180_000_000
    monkeypatch.setattr(paper_runner, "public_get", lambda *a: b"{}")
    monkeypatch.setattr(
        paper_runner,
        "parse_candles",
        lambda *a: (
            pd.DataFrame([dict(open_time=opened)]),
            None,
        ),
    )
    artifact = paper_runner.run_equity_paper(
        "fixture",
        calendar,
        seconds=0.05,
        root=tmp_path / "runs",
        snapshot=snapshot,
        engine=engine,
    )
    payload = json.loads(artifact.read_text())
    assert payload["bars"] == [] and payload["trace"]["orders"] == []
    events = [
        json.loads(r) for r in (artifact.parent / "observations.jsonl").read_text().splitlines()
    ]
    skipped = next(r for r in events if r["event"] == "STALE_STARTUP_CANDLE_SKIPPED")
    assert skipped["open_time"] == opened


def test_delayed_runner_accepts_delayed_candle_and_records_separate_contract(tmp_path, monkeypatch):
    calendar, snapshot, engine, _ = setup_runner(tmp_path, monkeypatch)
    opened = int(pd.Timestamp("2026-01-09 09:15", tz="Asia/Kolkata").value // 1000)
    stamps = count(opened + 60_000_000 + 43_000_000, 10_000)
    monkeypatch.setattr(paper_runner.time, "time_ns", lambda: next(stamps) * 1000)
    raw_quote = json.dumps(
        dict(
            chart=dict(
                result=[
                    dict(
                        meta=dict(
                            symbol="RELIANCE.NS",
                            currency="INR",
                            exchangeTimezoneName="Asia/Kolkata",
                            regularMarketTime=(opened + 61_000_000) // 1_000_000,
                            regularMarketPrice=100.0,
                        )
                    )
                ]
            )
        )
    ).encode()
    monkeypatch.setattr(paper_runner, "public_get", lambda *a: raw_quote)
    monkeypatch.setattr(
        paper_runner,
        "parse_candles",
        lambda *a: (
            pd.DataFrame(
                [
                    dict(open_time=stamp, open=100, high=101, low=99, close=100, volume=1000)
                    for stamp in (opened + 60_000_000, opened, opened - 60_000_000)
                ]
            ),
            None,
        ),
    )
    artifact = paper_runner.run_equity_paper(
        "delayed_fixture",
        calendar,
        seconds=0.05,
        root=tmp_path / "runs",
        snapshot=snapshot,
        engine=engine,
        timing="delayed_public",
    )
    payload = json.loads(artifact.read_text())
    assert payload["acceptance_scope"] == "delayed_public_simulation_only"
    assert payload["purpose"] == "delayed_public_data_simulation"
    assert payload["config"]["max_event_skew_us"] == 120_000_000
    assert len(payload["bars"]) == 1 and payload["trace"]["orders"] == []
    observed = EquityClosedCandle.model_validate(payload["bars"][0])
    assert observed.event_time == opened + 60_000_000
    assert observed.received_time - observed.event_time >= 43_000_000
