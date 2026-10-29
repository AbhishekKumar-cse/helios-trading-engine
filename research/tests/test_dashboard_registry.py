import runpy
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest
from test_registry_results import registry as _registry_fixture

from helios.dashboard.registry import market_label, registry_rows, report_html

registry = pytest.fixture(_registry_fixture.__wrapped__)


@pytest.mark.parametrize(
    "spec,source,expected",
    [
        ({}, "nse_public_minutes_v2", "nse_cash"),
        ({"market": "binance_spot"}, "nse_official_daily", "nse_cash"),
        ({}, "binance_spot", "binance_spot"),
        ({}, "bybit_spot", "bybit_spot"),
        ({"is_synthetic": True}, None, "synthetic"),
        ({}, None, "Unspecified"),
    ],
)
def test_market_uses_dataset_identity_and_keeps_missing_metadata_unknown(spec, source, expected):
    assert market_label(spec, source) == expected


def test_registry_includes_draft_definitions_without_invented_measurements(registry):
    definitions, _ = registry_rows(registry)
    row = next(d for d in definitions if d["Alpha"] == "t_result_alpha")
    assert row["Measurement"] == "DRAFT" and row["Report"] is None and row["Attempts"] == 0


def test_report_rejects_path_or_noncanonical_identifier_before_database():
    with pytest.raises(ValueError, match="UUID"):
        report_html("../../.env")


def test_streamlit_registry_and_filters_render_read_only_fixture():
    definitions = [
        dict(
            Alpha="test_alpha",
            Version=1,
            Name="Test alpha",
            Family="H-HOURLY",
            Provenance="HUMAN",
            Measurement="INVALID",
            Selection="REJECTED",
            Attempts=1,
            Synthetic=False,
            Report="?run=00000000-0000-0000-0000-000000000001",
        )
    ]
    attempts = [
        dict(
            Alpha="test_alpha",
            Version=1,
            Split="VALID",
            Status="INVALID",
            Sharpe=None,
            Fitness=None,
            Run="00000000-0000-0000-0000-000000000001",
            Report=definitions[0]["Report"],
        )
    ]
    with patch("helios.dashboard.registry.read_registry", return_value=(definitions, attempts)):
        app = AppTest.from_file(
            str(Path("dashboards/streamlit/app.py").resolve()), default_timeout=30
        )
        app.query_params["page"] = "registry"
        app.run()
        assert not app.exception
        assert app.metric[0].value == "1" and len(app.dataframe[0].value) == 1
        app.text_input[0].set_value("absent").run()
        assert not app.exception and app.dataframe[0].value.empty


def test_connection_error_does_not_expose_settings_or_traceback():
    with patch(
        "helios.dashboard.registry.read_registry", side_effect=RuntimeError("secret-password")
    ):
        app = AppTest.from_file(
            str(Path("dashboards/streamlit/app.py").resolve()), default_timeout=30
        )
        app.query_params["page"] = "registry"
        app.run()
    assert not app.exception and app.error
    assert "secret-password" not in app.error[0].value


def test_spawn_reimport_never_renders_ui_or_reads_database():
    # Streamlit's test runner can leave the page as __main__.__file__. Spawn
    # imports that path as __mp_main__; it must not execute the page again.
    with (
        patch("streamlit.set_page_config", side_effect=AssertionError("unexpected UI")),
        patch(
            "helios.dashboard.registry.read_registry", side_effect=AssertionError("unexpected DB")
        ),
    ):
        runpy.run_path(str(Path("dashboards/streamlit/app.py").resolve()), run_name="__mp_main__")


def test_spawn_worker_with_dashboard_as_main_never_boots_the_page(monkeypatch):
    import os
    import sys

    from test_sim_many import process_probe

    from helios.registry.results import Split
    from helios.sim.evaluate import EvaluationConfig
    from helios.sim.many import EvaluationRequest, evaluate_many

    # Reproduce the CI entrypoint left by AppTest. A page boot would fail before
    # connecting to any database; a guarded spawn import does not read settings.
    monkeypatch.setattr(
        sys.modules["__main__"], "__file__", str(Path("dashboards/streamlit/app.py").resolve())
    )
    monkeypatch.setattr(sys.modules["__main__"], "__spec__", None)
    monkeypatch.setenv("POSTGRES_PORT", "invalid-for-spawn-regression")
    request = EvaluationRequest("test_dashboard_spawn", Split.VALID, 1, EvaluationConfig())
    result = evaluate_many([request], workers=1, worker=process_probe)[0]
    assert result.error is None and result.status == "SYNTHETIC_TEST"
    assert int(result.run_id) != os.getpid()
