"""Inventory must preserve scope, missing values and held-out data boundaries."""

import hashlib
import json
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from streamlit.testing.v1 import AppTest

from helios.dashboard.dataset_inventory import collect_inventory, field_info
from helios.dashboard.registry_tracker import registered_row


def registry_record(tmp_path, *, status="REJECTED", source="upstox_nse_research_prefix"):
    evidence = tmp_path / "reports_out/evaluations/run.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        json.dumps(
            dict(
                status=status,
                snapshot_id="a" * 64,
                costs=dict(
                    points=[
                        dict(multiplier=m, metrics=dict(metrics=dict(total_return=v)))
                        for m, v in [(1.0, 0.02), (2.0, 0.005)]
                    ]
                ),
                fills=[{}],
            )
        )
    )
    return dict(
        alpha_id="momentum",
        version=2,
        spec_json={"expression": "sign(return_1)"},
        horizon_family="H-MINUTE",
        run_id="run_1",
        split="valid",
        snapshot_id="a" * 64,
        status=status,
        gate_results={"G1": True, "G7": False},
        dirty=False,
        evaluation_json=dict(
            artifact="/old/workspace/reports_out/evaluations/run.json",
            artifact_sha256=hashlib.sha256(evidence.read_bytes()).hexdigest(),
            validity={"symbol": "RELIANCE"},
        ),
        sharpe=1.7,
        fitness=1.2,
        source=source,
        interval="1m",
        symbols=["RELIANCE", "BSE"],
    )


def test_registered_scope_is_run_instrument_not_entire_snapshot(tmp_path):
    record = registry_record(tmp_path)
    row = registered_row(record, tmp_path)
    assert row.stock == "RELIANCE" and row.version == "2" and row.run_id == "run_1"
    assert row.normal_return_pct == 2 and row.doubled_return_pct == 0.5
    assert row.sharpe == 1.7 and not row.eligible and row.market == "NSE"
    assert "G7" in row.blockers and row.evidence_status == "Hash verified"
    assert row.performance.startswith("Positive at both")


def test_invalid_or_tampered_artifacts_never_rank_or_invent_zero(tmp_path):
    record = registry_record(tmp_path, status="INVALID")
    row = registered_row(record, tmp_path)
    assert row.sharpe is row.fitness is row.normal_return_pct is row.trades is None
    record = registry_record(tmp_path)
    (tmp_path / "reports_out/evaluations/run.json").write_text("{}")
    row = registered_row(record, tmp_path)
    assert row.sharpe is row.normal_return_pct is row.doubled_return_pct is None
    assert not row.eligible and row.evidence_status == "Unavailable / changed"


def test_synthetic_positive_run_cannot_become_eligible(tmp_path):
    record = registry_record(tmp_path, status="PROMOTED", source="synthetic_correctness_fixture")
    record["gate_results"] = {"G1": True}
    row = registered_row(record, tmp_path)
    assert not row.eligible and row.market == "Synthetic" and "SYNTHETIC" in row.blockers


def test_draft_has_no_assumed_dataset_or_measurement(tmp_path):
    record = registry_record(tmp_path)
    record.update(
        run_id=None, snapshot_id=None, status=None, evaluation_json=None, sharpe=None, fitness=None
    )
    row = registered_row(record, tmp_path)
    assert row.study_screen == "DRAFT" and row.evidence_status == "Definition only"
    assert row.normal_return_pct is None and row.dataset_sha256 == ""


def test_inventory_uses_schema_and_footer_only_across_frequencies(tmp_path):
    base = tmp_path / "data/equities/nifty50/fixture"
    (base / "bars").mkdir(parents=True)
    entries = []
    for interval in ("1d", "60m"):
        path = base / f"bars/EQ1_{interval}.parquet"
        pq.write_table(
            pa.table({"close": [1.0, 2.0], "volume": [3.0, 4.0], "available_at": [1, 2]}), path
        )
        entries.append(
            dict(
                path=path.relative_to(base).as_posix(),
                symbol="EQ1",
                interval=interval,
                first_session="2023-01-01",
                last_session="2023-01-02",
            )
        )
    (base / "manifest.json").write_text(
        json.dumps(dict(files=entries, provider="Fixture public source"))
    )
    with (
        patch("pyarrow.parquet.read_table", side_effect=AssertionError("observation access")),
        patch("pyarrow.parquet.ParquetFile.read", side_effect=AssertionError("observation access")),
    ):
        datasets, issues = collect_inventory(tmp_path)
    assert not issues and len(datasets) == 2
    assert {d.frequency for d in datasets} == {"1d", "1h"}
    assert all(d.rows == 2 and d.symbols == ("EQ1",) and len(d.fields) == 3 for d in datasets)
    assert all("TEST remains sealed" in d.access and "uncertified" in d.status for d in datasets)
    assert {f["Category"] for f in datasets[0].fields} == {
        "Price",
        "Volume & flow",
        "Time & availability",
    }
    (base / "bars/EQ1_1d.parquet").unlink()
    datasets, issues = collect_inventory(tmp_path)
    assert not datasets and issues  # source failure is visible, not a fabricated coverage row


def test_wide_profit_matrix_is_one_logical_field_not_fifty_fake_fields(tmp_path):
    base = tmp_path / "reports_out/equity_research/nse_profit_growth_fields_fixture"
    base.mkdir(parents=True)
    pq.write_table(
        pa.table({"EQ1": [0.1], "EQ2": [0.2], "session_date": ["2023-01-02"]}),
        base / "profit_growth_fields.parquet",
    )
    (base / "protocol.json").write_text("{}")
    (base / "quarterly_profit_facts.json").write_text(
        json.dumps(
            [dict(symbol="EQ1", period_end="2022-12-31", profit_inr="3", available_at="2023-01-01")]
        )
    )
    datasets, issues = collect_inventory(tmp_path)
    assert not issues and len(datasets) == 2
    matrix = datasets[0]
    assert matrix.symbols == ("EQ1", "EQ2")
    assert [f["Field"] for f in matrix.fields] == ["profit_yoy_growth", "session_date"]
    assert matrix.rows == 1 and datasets[1].rows == 1


def test_raw_archive_does_not_claim_parsed_rows_or_fields(tmp_path):
    base = tmp_path / "data/bybit/trades"
    base.mkdir(parents=True)
    (base / "BTCUSDT2026-09-01.csv.gz").write_bytes(b"raw fixture")
    datasets, issues = collect_inventory(tmp_path)
    assert not issues and len(datasets) == 1
    assert datasets[0].rows is None and not datasets[0].fields


def test_tracker_keeps_crypto_rows_visible_and_filters_by_market(tmp_path):
    rows = [
        registered_row(registry_record(tmp_path), tmp_path),
        registered_row(registry_record(tmp_path, source="binance"), tmp_path),
    ]
    with (
        patch("helios.dashboard.tracker_page.PROJECT_ROOT", tmp_path),
        patch("helios.dashboard.tracker_page.refresh_tracker", return_value=(rows, [])),
    ):
        app = AppTest.from_string(
            "from helios.dashboard.tracker_page import render_tracker\nrender_tracker()",
            default_timeout=30,
        ).run()
        assert not app.exception and len(app.dataframe[0].value) == 2
        next(box for box in app.selectbox if box.label == "Market").set_value("Crypto").run()
        assert not app.exception and app.dataframe[0].value.Market.tolist() == ["Crypto"]


@pytest.mark.parametrize(
    "name,category",
    [
        ("available__volatility_24", "Quality & availability"),
        ("profit_yoy_growth", "Fundamental"),
        ("isin", "Identity & lineage"),
    ],
)
def test_field_classification(name, category):
    assert field_info(name, "double", "NSE")["Category"] == category
