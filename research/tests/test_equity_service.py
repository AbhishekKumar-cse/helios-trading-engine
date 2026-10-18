"""Observer continuity and closed-market evidence, without generated market data."""

import json
import urllib.error
from datetime import UTC, datetime

import pytest

from helios.equities import service


def test_suspend_or_process_pause_invalidates_continuous_uptime():
    clock = service.Continuity(10)
    assert clock.check(10, 100)
    assert clock.check(20, 110)
    assert not clock.check(21, 3710)  # monotonic can stop during host suspend
    assert not clock.check(100, 3789)  # process scheduling stall
    assert clock.gaps == 2


def test_observer_retains_terminal_failure_instead_of_losing_evidence(tmp_path, monkeypatch):
    calendar = tmp_path / "calendar.json"
    calendar.write_text("{}")

    def broken(*args):
        raise ValueError("invalid calendar")

    monkeypatch.setattr(service, "session_is_open", broken)
    with pytest.raises(ValueError, match="calendar"):
        service.observe_service(tmp_path / "runs", "failure_fixture", calendar, seconds=1)
    artifact = json.loads((tmp_path / "runs/failure_fixture/artifact.json").read_text())
    assert artifact["status"] == "FAILED" and not artifact["uptime_24h_observed"]
    assert artifact["observed_paper_fills"] == 0


def test_official_normal_calendar_rejects_holiday_and_weekend(tmp_path):
    calendar = tmp_path / "calendar.json"
    calendar.write_text(json.dumps({"CM": [{"tradingDate": "26-Jan-2026"}]}))
    assert not service.session_is_open(datetime(2026, 1, 26, 5, tzinfo=UTC), calendar)
    assert not service.session_is_open(datetime(2026, 10, 18, 5, tzinfo=UTC), calendar)
    assert service.session_is_open(datetime(2026, 1, 27, 5, tzinfo=UTC), calendar)


def test_observer_access_denial_stops_without_retry_or_false_uptime(tmp_path, monkeypatch):
    calendar = tmp_path / "calendar.json"
    calendar.write_text("{}")
    monkeypatch.setattr(service, "session_is_open", lambda *a: True)
    monkeypatch.setattr(service.time, "sleep", lambda *a: None)
    calls = []

    def denied(url):
        calls.append(url)
        raise urllib.error.HTTPError(url, 403, "denied", {}, None)

    monkeypatch.setattr(service, "public_get", denied)
    result = service.observe_service(tmp_path / "runs", "denied_fixture", calendar, seconds=2)
    artifact = json.loads((result / "artifact.json").read_text())
    assert len(calls) == 1 and artifact["status"] == "STOPPED"
    assert artifact["failures"] == 1 and not artifact["uptime_24h_observed"]
    assert artifact["observed_paper_fills"] == 0
