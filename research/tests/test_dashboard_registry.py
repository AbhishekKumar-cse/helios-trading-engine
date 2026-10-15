from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest
from test_registry_results import registry as _registry_fixture

from helios.dashboard.registry import registry_rows, report_html

registry = pytest.fixture(_registry_fixture.__wrapped__)


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
        ).run()
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
        ).run()
    assert not app.exception and app.error
    assert "secret-password" not in app.error[0].value
