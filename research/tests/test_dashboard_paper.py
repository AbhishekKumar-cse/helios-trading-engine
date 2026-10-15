from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest
from test_paper_runtime import BASE, bar, definition, raw
from test_paper_store import paper_engine as _paper_engine

from helios.alpha.definition import register_alpha_definition
from helios.common.config import config_hash
from helios.common.lineage import RunContext
from helios.dashboard.paper import paper_rows
from helios.paper.config import smoke_config
from helios.paper.runtime import PaperRuntime
from helios.paper.store import PaperStore
from helios.sim.loss_risk import PostgresTripStore

paper_engine = pytest.fixture(_paper_engine.__wrapped__)


@pytest.fixture
def session(paper_engine, connection):
    config = smoke_config("test_dashboard_paper", "d" * 64).model_copy(
        update=dict(alpha_id="t_dashboard_paper")
    )
    selected = definition(config)
    register_alpha_definition(connection, selected)
    context = RunContext(
        "a" * 40, False, config_hash(config), config.stream_id, 0, datetime.now(UTC)
    )
    store = PaperStore(paper_engine, config, context)
    runtime = PaperRuntime(config, selected, context.code_commit, PostgresTripStore(paper_engine))
    return config, store, runtime


def test_paper_view_tracks_checkpoints_without_mixing_backtests(session, connection):
    config, store, runtime = session
    empty = paper_rows(connection, config.run_id)
    assert empty["pnl"] is None and empty["positions"] == [] and empty["orders"] == []
    runtime.closed(bar(0, "100"))
    runtime.closed(bar(1, "101"))
    store.save(runtime)
    pending = paper_rows(connection, config.run_id)
    assert pending["run"]["mode"] == "PAPER" and pending["run"]["is_simulated"]
    assert len(pending["orders"]) == 1 and not pending["halted"]
    runtime.message(raw(2, closed=False, close="102"), (BASE + 120_000) * 1000 + 2_010_000)
    store.save(runtime)
    filled = paper_rows(connection, config.run_id)
    assert filled["orders"] == [] and filled["positions"][0]["net_qty"] != 0
    assert filled["pnl"]["ts"] > pending["pnl"]["ts"]
    assert filled["pnl"]["fees"] > 0
    with pytest.raises(ValueError, match="unknown"):
        paper_rows(connection, "hand_20261015")


def test_paper_page_refreshes_and_renders_simulation_and_missing_data(session, connection):
    config, store, runtime = session
    with (
        patch("helios.dashboard.registry.read_registry", return_value=([], [])),
        patch(
            "helios.dashboard.paper_page.read_paper",
            side_effect=lambda *_: paper_rows(connection, config.run_id),
        ),
    ):
        app = AppTest.from_file(
            str(Path("dashboards/streamlit/app.py").resolve()), default_timeout=30
        ).run()
        app.sidebar.radio[0].set_value("Paper trading").run()
        assert not app.exception
        assert any("is_simulated = true" in c.value for c in app.caption)
        assert "No P&L checkpoint" in app.warning[0].value
        runtime.closed(bar(0, "100"))
        runtime.closed(bar(1, "101"))
        store.save(runtime)
        app.run()
        assert not app.exception and len(app.metric) == 4
        assert len(app.dataframe[1].value) == 1
        assert any("stale" in w.value for w in app.warning)


def test_paper_database_error_is_sanitized():
    with (
        patch("helios.dashboard.registry.read_registry", return_value=([], [])),
        patch("helios.dashboard.paper_page.read_paper", side_effect=RuntimeError("secret")),
    ):
        app = AppTest.from_file(
            str(Path("dashboards/streamlit/app.py").resolve()), default_timeout=30
        ).run()
        app.sidebar.radio[0].set_value("Paper trading").run()
        assert not app.exception and app.error
        assert "secret" not in app.error[0].value
