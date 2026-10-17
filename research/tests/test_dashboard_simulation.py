import json
from decimal import Decimal, localcontext
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from helios.dashboard.simulation import DemoOptions, run_demo, synthetic_rows
from helios.dashboard.simulation_page import replay_view
from helios.data.binance import sha256_file
from helios.sim.paper import rounded


@pytest.fixture
def demo(tmp_path):
    return run_demo(DemoOptions(bars=96), root=tmp_path)


def test_demo_uses_shared_fills_fees_and_retains_its_exact_inputs(demo):
    artifact = demo.artifact
    assert artifact.config.experiment_id is None
    assert sha256_file(Path(artifact.config.csv_path)) == artifact.config.csv_sha256
    assert (
        json.loads(demo.path.read_text())["purpose"] == "synthetic_interactive_sandbox_not_research"
    )
    opens = {bar.open_time: bar.open for bar in artifact.bars}
    fills = [r.fill for r in artifact.trace.reports if r.fill is not None]
    assert len(fills) > 2
    with localcontext() as context:
        context.prec = 100
        for fill in fills:
            side = 1 if fill.side.value == "BUY" else -1
            assert fill.price == rounded(opens[fill.timestamp] * (1 + side * Decimal(".0002")))
            assert fill.fee == rounded(fill.quantity * fill.price * Decimal(".001"))


def test_replay_never_shows_the_next_opening_fill_at_a_close(demo):
    trace = demo.artifact.trace
    assert replay_view(demo, 0)["pnl"] == 0
    assert not replay_view(demo, demo.options.lookback + 1)["fills"]
    for cursor in range(1, len(demo.artifact.bars) + 1):
        view = replay_view(demo, cursor)
        with localcontext() as context:
            context.prec = 100
            assert (
                sum((Decimal(f["Fee"]) for f in view["fills"]), Decimal(0))
                == trace.snapshots[cursor - 1].fees
            )
    assert len(replay_view(demo, demo.options.bars)["fills"]) > 2
    with pytest.raises(ValueError):
        replay_view(demo, -1)


def test_seeded_prices_and_signals_use_only_current_and_past_closes():
    options = DemoOptions()
    rows = synthetic_rows(options)
    assert rows == synthetic_rows(options)
    assert rows != synthetic_rows(options.model_copy(update=dict(seed=43)))
    for index, row in enumerate(rows):
        if index < options.lookback:
            assert row["decision_alpha"] == ""
        else:
            current, past = Decimal(row["close"]), Decimal(rows[index - options.lookback]["close"])
            assert int(row["decision_alpha"]) == (current > past) - (current < past)


def test_demo_loss_guard_latches_without_opening_new_orders(tmp_path):
    run = run_demo(
        DemoOptions(
            scenario="Sell-off and recovery",
            strategy="Buy and hold",
            allocation_pct=80,
            daily_loss_pct=0.1,
            bars=96,
        ),
        root=tmp_path,
    )
    assert len(run.trips) == 1 and run.trips[0].reason.value == "DAILY_LOSS_LIMIT"
    assert all(o.request.timestamp < run.trips[0].timestamp for o in run.artifact.trace.orders)
    assert replay_view(run, run.options.bars)["halted"]


def test_default_page_is_populated_without_database_and_controls_replay(demo):
    with (
        patch("helios.dashboard.simulation_page.run_demo", return_value=demo) as execute,
        patch("helios.dashboard.registry.read_registry", side_effect=AssertionError("DB read")),
    ):
        app = AppTest.from_file(
            str(Path("dashboards/streamlit/app.py").resolve()), default_timeout=30
        ).run()
        assert not app.exception
        assert app.sidebar.radio[0].value == "Simulation"
        assert len(app.metric) == 5 and int(app.metric[3].value) > 0
        assert len(app.get("vega_lite_chart")) == 2
        next(b for b in app.button if b.label == "Reset replay").click().run()
        assert not app.exception and app.session_state.sandbox_cursor == 0
        assert app.metric[3].value == "0"
        next(b for b in app.button if b.label == "Next bar").click().run()
        assert not app.exception and app.session_state.sandbox_cursor == 1
        next(s for s in app.selectbox if s.label == "Strategy").set_value("Mean reversion")
        next(b for b in app.button if b.label == "Run simulation").click().run()
        assert not app.exception and execute.call_count == 2
        assert execute.call_args.args[0].strategy == "Mean reversion"
        assert app.session_state.sandbox_playing
        next(b for b in app.button if b.label == "Pause").click().run()
        assert not app.exception and not app.session_state.sandbox_playing
