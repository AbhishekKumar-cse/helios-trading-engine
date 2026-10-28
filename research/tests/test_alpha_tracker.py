"""Tracker performance labels must preserve leads without inventing eligibility."""

import csv
import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from helios.dashboard.alpha_tracker import (
    TrackerRow,
    collect_rows,
    digest,
    performance_label,
    refresh_tracker,
    write_csv,
)


def row(**changes):
    item = TrackerRow(
        record_id="bse:parity",
        alpha="bse_body60_v1",
        dataset="BSE official daily",
        dataset_sha256="a" * 64,
        stock="BSE",
        scope="Single stock · historical parity",
        split="Exposed TRAIN",
        units="Whole shares",
        period="2023",
        performance="Positive at both costs · exploratory",
        study_screen="Historical parity only",
        eligible=False,
        normal_return_pct=2.07,
        doubled_return_pct=0.56,
        sharpe=0.97,
        fitness=None,
        trades=54,
        blockers="Fresh confirmation pending",
        next_step="Collect future observations",
        evidence="reports_out/bse/candidate.json",
        evidence_sha256="b" * 64,
    )
    return replace(item, **changes)


def test_profitability_is_separate_from_eligibility_and_missing_is_not_zero():
    assert performance_label(0.02, 0.005).startswith("Positive at both")
    assert performance_label(0.01, -0.005) == "Positive base · cost fragile"
    assert performance_label(None, None) == "Not measured"
    assert performance_label(0.0, 0.0).startswith("Cash only")
    assert row().eligible is False


def test_atomic_csv_preserves_unicode_missing_values_and_all_failed_rows(tmp_path):
    path = tmp_path / "alpha_tracker.csv"
    write_csv(
        path,
        [
            row(),
            row(record_id="failed", normal_return_pct=-3.0),
            row(record_id="future", normal_return_pct=None, doubled_return_pct=None),
        ],
    )
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 3 and rows[0]["eligible"] == "False"
    assert rows[2]["normal_return_pct"] == ""  # never invent a zero forward return
    assert rows[1]["normal_return_pct"] == "-3.0"
    assert not list(tmp_path.glob("alpha_tracker.csv.*"))


def test_failed_replace_keeps_old_csv_and_removes_temporary_file(tmp_path):
    path = tmp_path / "alpha_tracker.csv"
    path.write_text("old snapshot")
    with patch("helios.dashboard.alpha_tracker.os.replace", side_effect=OSError("unavailable")):
        with pytest.raises(OSError):
            write_csv(path, [row()])
    assert path.read_text() == "old snapshot" and not list(tmp_path.glob("alpha_tracker.csv.*"))


def test_incomplete_study_is_visible_and_not_invented(tmp_path):
    directory = tmp_path / "reports_out/equity_research/interrupted"
    directory.mkdir(parents=True)
    (directory / "protocol.json").write_text(json.dumps({"version": "official_panel_drift_v1"}))
    rows, issues = collect_rows(tmp_path)
    assert not rows and "incomplete" in issues[0]


def test_malformed_source_schema_is_a_notice_instead_of_a_page_crash(tmp_path):
    directory = tmp_path / "reports_out/equity_research/malformed"
    directory.mkdir(parents=True)
    (directory / "protocol.json").write_text("[]")
    rows, issues = collect_rows(tmp_path)
    assert not rows and "integrity" in issues[0]


@pytest.mark.parametrize(
    "version,alpha,symbol,isin",
    [
        ("single_stock_compression_v1", "reliance_compression60_v1", "RELIANCE", "INE002A01018"),
        ("single_stock_pressure_v1", "icici_pressure60_v1", "ICICIBANK", "INE090A01021"),
    ],
)
def test_stock_adapter_requires_all_audited_accounts_and_rejects_tampering(
    tmp_path, version, alpha, symbol, isin
):
    directory = tmp_path / "reports_out/equity_research/compression"
    directory.mkdir(parents=True)
    (directory / "records.parquet").write_bytes(b"synthetic hash fixture, not market data")
    protocol = dict(
        version=version,
        alpha_id=alpha,
        symbol=symbol,
        isin=isin,
        train=["2023-01-01", "2023-12-31"],
    )
    (directory / "protocol.json").write_text(json.dumps(protocol))
    accounts = {}
    for unit in ("whole", "fractional"):
        for cost in (1, 2):
            for name in ("candidate", "always", "frequency"):
                key = f"{unit}_cost{cost}_{name}"
                accounts[key] = dict(net_return=-0.01 * cost, sharpe=-1.0, trades=10)
                (directory / f"{key}.json").write_text(json.dumps({"summary": accounts[key]}))
    result = dict(
        protocol_sha256=digest(directory / "protocol.json"),
        dataset_sha256=digest(directory / "records.parquet"),
        eligible=False,
        accounts=accounts,
        screen_passed=False,
        blockers=["Exposed history"],
        actual_orders=0,
        actual_fills=0,
        registry_writes=0,
        valid_evaluations=0,
        test_accesses=0,
    )
    (directory / "result.json").write_text(json.dumps(result))
    audit = dict(
        passed=True,
        accounts_replayed=12,
        protocol_sha256=result["protocol_sha256"],
        dataset_sha256=result["dataset_sha256"],
        result_sha256=digest(directory / "result.json"),
    )
    (directory / "independent_verification.json").write_text(json.dumps(audit))
    manifest = {p.name: digest(p) for p in directory.iterdir()}
    (directory / "artifact_hashes.json").write_text(json.dumps(manifest))
    rows, issues = collect_rows(tmp_path)
    assert not issues and len(rows) == 2
    assert rows[0].stock == symbol and rows[0].normal_return_pct == -1.0
    assert not any(r.eligible for r in rows)
    (directory / "fractional_cost2_frequency.json").write_text("{}")
    rows, issues = collect_rows(tmp_path)
    assert not rows and "integrity" in issues[0]


def test_hash_tampering_is_reported_without_reusing_stale_positive_rows(tmp_path):
    directory = tmp_path / "reports_out/equity_research/tampered"
    directory.mkdir(parents=True)
    path = directory / "protocol.json"
    path.write_text(json.dumps({"version": "official_cost_hurdle_v1"}))
    (directory / "result.json").write_text("{}")
    (directory / "artifact_hashes.json").write_text(json.dumps({"protocol.json": "0" * 64}))
    rows, issues = refresh_tracker(tmp_path)
    assert not rows and "integrity" in issues[0]
    assert (tmp_path / "local_state/alpha_tracker.csv").exists()
    assert digest(path) != "0" * 64


def test_tracker_filters_and_pending_state_do_not_query_database(tmp_path):
    pending = row(
        record_id="bse:forward",
        scope="Single stock · forward plan",
        split="Forward · not started",
        performance="Forward not started",
        normal_return_pct=None,
        doubled_return_pct=None,
        sharpe=None,
        trades=None,
    )
    fixture = [
        row(),
        pending,
        row(
            record_id="bad",
            alpha="failed_alpha",
            stock="OTHER",
            dataset="OTHER official daily",
            normal_return_pct=-3.0,
            study_screen="Failed original screen",
        ),
    ]
    with (
        patch("helios.dashboard.tracker_page.PROJECT_ROOT", tmp_path),
        patch("helios.dashboard.tracker_page.refresh_tracker", return_value=(fixture, [])),
        patch(
            "helios.dashboard.registry.read_registry", side_effect=AssertionError("unexpected DB")
        ),
    ):
        app = AppTest.from_file(
            str(Path("dashboards/streamlit/app.py").resolve()), default_timeout=30
        )
        app.query_params["page"] = "tracker"
        app.run()
        assert not app.exception and app.title[0].value == "Alpha tracker"
        assert app.metric[2].value == "0" and len(app.dataframe[0].value) == 3
        app.text_input[0].set_value("BSE").run()
        assert len(app.dataframe[0].value) == 2
        next(box for box in app.selectbox if box.label == "Show").set_value("Forward plans").run()
        table = app.dataframe[0].value
        assert len(table) == 1 and table["Normal %"].isna().all()
        assert not app.exception


def test_verified_stock_rows_keep_positive_history_and_unmeasured_forward_separate(tmp_path):
    directory = tmp_path / "reports_out/equity_research/stock"
    directory.mkdir(parents=True)
    (directory / "bse_exposed_2022_2023.parquet").write_bytes(b"synthetic dataset hash fixture")
    protocol = {"version": "bse_single_stock_v1", "forward_plan": {"not_before": "2026-10-26"}}
    (directory / "protocol.json").write_text(json.dumps(protocol))
    historical = {
        "cost1": {"net_return": 0.0207, "sharpe": 0.97, "trades": 54},
        "cost2": {"net_return": 0.0056, "sharpe": 0.27, "trades": 54},
    }
    for key, summary in historical.items():
        (directory / f"historical_{key}.json").write_text(json.dumps({"summary": summary}))
    candidate = dict(
        protocol_sha256=digest(directory / "protocol.json"),
        historical_parity_passed=True,
        eligible=False,
        forward_evaluations=0,
        forward_sessions_observed=0,
        collector_running=False,
        future_status="NOT_STARTED",
        alpha_id="bse_body60_v1",
        dataset_id="BSE fixture",
        dataset_sha256=digest(directory / "bse_exposed_2022_2023.parquet"),
        historical=historical,
    )
    (directory / "candidate.json").write_text(json.dumps(candidate))

    def manifest():
        (directory / "artifact_hashes.json").write_text(
            json.dumps(
                {f.name: digest(f) for f in directory.iterdir() if f.name != "artifact_hashes.json"}
            )
        )

    manifest()
    rows, issues = collect_rows(tmp_path)
    assert not issues and len(rows) == 2
    assert rows[0].normal_return_pct == pytest.approx(2.07) and not rows[0].eligible
    assert rows[1].normal_return_pct is None and rows[1].trades is None
    candidate["forward_sessions_observed"] = 50
    (directory / "candidate.json").write_text(json.dumps(candidate))
    manifest()
    rows, issues = collect_rows(tmp_path)
    assert not rows and issues  # cannot misrepresent an unsupported future state as zero observed
