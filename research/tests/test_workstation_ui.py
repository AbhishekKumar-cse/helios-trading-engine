"""Preview acknowledgement, navigation and honest unavailable diagnostics."""

from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from helios.dashboard.nse_backtest import DatasetChoice
from helios.dashboard.portfolio_page import compare


def test_changed_preview_requires_new_acknowledgement(tmp_path):
    dataset = DatasetChoice(tmp_path / "data", "1m", ("EXAMPLE",), "a" * 64)
    with (
        patch("helios.dashboard.lab_page.PROJECT_ROOT", tmp_path),
        patch("helios.dashboard.lab_page.datasets", return_value=[dataset]),
    ):
        app = AppTest.from_string(
            "from helios.dashboard.lab_page import render_lab\nrender_lab()", default_timeout=30
        ).run()
        assert not app.exception
        next(x for x in app.text_input if x.label == "Hypothesis").set_value(
            "A frozen fixture hypothesis about continuation after costs"
        ).run()
        app.checkbox[0].check().run()
        assert not next(b for b in app.button if b.label == "Run now").disabled
        next(x for x in app.text_input if x.label.startswith("$lookback")).set_value("2, 3").run()
        assert not app.exception and not app.checkbox[0].value
        assert next(b for b in app.button if b.label == "Run now").disabled


def test_empty_queue_does_not_claim_a_running_worker(tmp_path):
    with patch("helios.dashboard.tasks_page.PROJECT_ROOT", tmp_path):
        app = AppTest.from_string(
            "from helios.dashboard.tasks_page import render_tasks\nrender_tasks()",
            default_timeout=30,
        ).run()
    assert not app.exception and app.metric[1].value == "0"
    assert next(b for b in app.button if b.label == "Start queued jobs").disabled


def test_template_draft_survives_leaving_and_returning_to_lab(tmp_path):
    dataset = DatasetChoice(tmp_path / "data", "1m", ("EXAMPLE",), "a" * 64)
    with (
        patch("helios.dashboard.lab_page.PROJECT_ROOT", tmp_path),
        patch("helios.dashboard.lab_page.datasets", return_value=[dataset]),
    ):
        app = AppTest.from_string(
            "import streamlit as st\n"
            "from helios.dashboard.lab_page import render_lab\n"
            "if st.radio('Page', ['Lab', 'Other']) == 'Lab':\n"
            "    render_lab()",
            default_timeout=30,
        ).run()
        # Streamlit widget values disappear when their page is not rendered.
        draft = "clip(sign($field - lag($field, $lookback)), 0, 0.5)"
        app.text_area[0].set_value(draft).run()
        app.radio[0].set_value("Other").run()
        app.radio[0].set_value("Lab").run()
        assert not app.exception and app.text_area[0].value == draft


def account(symbol="A", days=("2026-01-12", "2026-01-13")):
    return dict(
        protocol=dict(
            manifest_sha256="a" * 64,
            interval="1m",
            options=dict(start="2026-01-12", end="2026-01-13", capital="100000", symbol=symbol),
            cash_carries_between_flat_sessions=True,
        ),
        result=dict(
            scenarios={
                "1": dict(
                    daily=[dict(day=day, net_return=0.001, end_cash="100100") for day in days]
                )
            }
        ),
    )


def test_comparison_requires_matched_observed_calendars_and_sufficient_overlap():
    frame, correlation = compare([account(), account("B")])
    assert len(frame) == 2 and correlation.empty
    assert frame["Mean account equity"].tolist() == [100100, 100100]
    with pytest.raises(ValueError, match="calendars"):
        compare([account(), account("B", ("2026-01-12",))])
