"""Navigation, catalogue filtering and formula-only retained-result regressions."""

import json
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from helios.dashboard.dataset_inventory import DatasetInventory, field_info
from helios.data.equities import sha256

APP = str(Path("dashboards/streamlit/app.py").resolve())

DATASETS = [
    DatasetInventory(
        "fixture",
        "NSE prices fixture",
        "NSE",
        "Prices & volume",
        "1d",
        "Fixture provider",
        "Uncertified fixture",
        "TRAIN/VALID only",
        3,
        ("EQ1",),
        "2023",
        tuple(field_info(name, "double", "NSE") for name in ("close", "volume")),
        (),
        "fixture",
        "",
    )
]


def test_navigation_clears_report_and_honours_new_url_without_database():
    with (
        patch("helios.dashboard.datasets_page.collect_inventory", return_value=(DATASETS, [])),
        patch("helios.dashboard.registry.report_html", return_value="<p>Retained report</p>"),
        patch(
            "helios.dashboard.registry.read_registry", side_effect=AssertionError("unexpected DB")
        ),
        patch("helios.dashboard.paper_page.read_paper", return_value={"runs": []}),
    ):
        app = AppTest.from_file(APP, default_timeout=30)
        app.query_params["run"] = "00000000-0000-0000-0000-000000000001"
        app.run()
        assert not app.exception and app.sidebar.radio[0].value == "Alpha registry"
        app.sidebar.radio[0].set_value("Datasets").run()
        assert not app.exception and "run" not in app.query_params
        assert app.query_params["page"] == "datasets"
        # An externally opened URL must override the last sidebar selection.
        app.query_params["page"] = "paper"
        app.run()
        assert not app.exception and app.sidebar.radio[0].value == "Paper trading"
        assert app.title[0].value == "Paper monitor"


def test_dataset_search_and_empty_state_do_not_run_research():
    with (
        patch("helios.dashboard.registry.read_registry", side_effect=AssertionError("DB read")),
        patch("helios.dashboard.datasets_page.collect_inventory", return_value=(DATASETS, [])),
    ):
        app = AppTest.from_file(APP, default_timeout=30)
        app.query_params["page"] = "datasets"
        app.run()
        assert not app.exception and len(app.dataframe[1].value) == 2
        app.text_input[0].set_value("volume").run()
        assert not app.exception and app.dataframe[1].value.Field.tolist() == ["volume"]
        app.text_input[0].set_value("no_such_field").run()
        assert not app.exception and len(app.dataframe) == 2  # inventory + declared contracts
        assert any("No fields match" in item.value for item in app.info)


def test_formula_round_renders_without_inventing_model_calibration(tmp_path):
    directory = tmp_path / "reports_out/equity_research/nse_formula_fixture"
    directory.mkdir(parents=True)
    protocol = directory / "protocol.json"
    protocol.write_text("{}")
    artifact = directory / "artifact.json"
    artifact.write_text(
        json.dumps(
            dict(
                coverage=dict(complete=0, expected=1, excluded=[]),
                fills=[],
                fees_total_inr="0",
                series=[],
            )
        )
    )
    row = dict(
        symbol="EQ1",
        candidate="fixture",
        status="INVALID",
        sharpe=None,
        fitness=None,
        gates={"G1": False},
        run_id="fixture",
        artifact=str(artifact),
        artifact_sha256=sha256(artifact),
    )
    (directory / "summary.json").write_text(
        json.dumps(
            dict(
                protocol_sha256=sha256(protocol),
                results=[row],
                interval="1m",
                test_accesses=0,
                promoted=0,
            )
        )
    )
    with patch("helios.dashboard.equity_research.PROJECT_ROOT", tmp_path):
        app = AppTest.from_string(
            "from helios.dashboard.equity_research import render_equity_research\n"
            "render_equity_research('EQ1')",
            default_timeout=30,
        ).run()
    assert not app.exception and not app.error
    assert app.dataframe[0].value.Candidate.tolist() == ["fixture"]
    assert any("no rankable" in item.value for item in app.info)
