import hashlib
import json
from decimal import Decimal as D

import pytest
from sqlalchemy import text
from test_backtest_runner import config, inputs
from test_backtest_runner import engine as _engine_fixture
from test_loss_risk import Store

from helios.backtest.engine import simulate
from helios.backtest.report import (
    BacktestReportError,
    accounting_summary,
    generate_backtest_report,
    verified_artifact,
)
from helios.backtest.runner import BacktestArtifact, preregister, run_backtest
from helios.common.lineage import RunContext

engine = pytest.fixture(_engine_fixture.__wrapped__)


def test_cost_attribution_drawdown_exposure_and_fill_count_match_hand_scenario():
    selected = config()
    batch = inputs(selected)
    artifact = BacktestArtifact(
        config=selected,
        context=RunContext.capture(selected, selected.snapshot_id, 0, reported=False),
        input_sha256=batch.sha256,
        bars=batch.bars,
        signals=batch.signals,
        trace=simulate(selected, batch.bars, batch.signals, Store()),
    )
    summary = accounting_summary(artifact)
    for key, expected in dict(
        gross_pnl="20",
        execution_gross_pnl="19.89",
        net_pnl="19.340022",
        fees=".549978",
        slippage=".11",
        max_drawdown="50",
        max_gross_exposure="250",
        final_net_exposure="-90",
        turnover_over_initial_capital=".549978",
    ).items():
        assert D(summary[key]) == D(expected), key
    assert summary["max_drawdown_duration_us"] == 5 * 3_600_000_000
    assert summary["order_count"] == summary["fill_count"] == summary["taker_fills"] == 3
    assert summary["maker_fills"] == summary["risk_rejections"] == 0
    assert summary["unavailable_signals"] == 7
    assert D(summary["gross_series"][0]) == 0  # next open at equal time is still later
    assert D(summary["gross_series"][-1]) == 20
    assert summary["per_coin"][0]["symbol"] == "BTCUSDT"

    # A final short-friendly close recovers the earlier peak. The recovery
    # observation belongs to the elapsed drawdown, not only the prior low.
    recovery_bars = batch.bars[:-1] + (
        batch.bars[-1].model_copy(update=dict(close=D("50"), low=D("40"))),
    )
    recovered = artifact.model_copy(
        update=dict(
            bars=recovery_bars,
            trace=simulate(selected, recovery_bars, batch.signals, Store()),
        )
    )
    assert accounting_summary(recovered)["max_drawdown_duration_us"] == 5 * 3_600_000_000


def test_report_verifies_database_evidence_archives_and_generates_without_rerun(engine, tmp_path):
    selected = preregister(config("test_backtest_report"), engine=engine, reported=False)
    run_backtest(selected, engine=engine, output_dir=tmp_path, reported=False)
    path = generate_backtest_report(selected.run_id, engine=engine, output_root=tmp_path)
    original = path.read_bytes()
    assert generate_backtest_report(selected.run_id, engine=engine, output_root=tmp_path) == path
    assert path.read_bytes() == original
    page = original.decode()
    for label in (
        "BACKTEST",
        "SIMULATED",
        "Synthetic correctness fixture",
        "Per coin",
        "Recorded fills",
        "Drawdown",
        "bar_close_proxy",
        "19.340022",
        "gross",
    ):
        assert label.lower() in page.lower()
    folder = path.parent
    assert (folder / f"report-{hashlib.sha256(original).hexdigest()}.html").is_file()
    summaries = list(folder.glob("summary-*.json"))
    assert len(summaries) == 1
    saved = json.loads(summaries[0].read_text())
    assert saved["summary"]["fill_count"] == 3
    assert (
        saved["source_commit"] == verified_artifact(engine, selected.run_id)[0].context.code_commit
    )


def test_no_fill_report_keeps_zero_separate_from_unavailable_signals():
    from helios.common.types import AlphaStatus

    selected = config()
    batch = inputs(selected)
    signals = tuple(
        s.model_copy(update=dict(status=AlphaStatus.UNAVAILABLE, value=None)) for s in batch.signals
    )
    artifact = BacktestArtifact(
        config=selected,
        context=RunContext.capture(selected, selected.snapshot_id, 0, reported=False),
        input_sha256=batch.sha256,
        bars=batch.bars,
        signals=signals,
        trace=simulate(selected, batch.bars, signals, Store()),
    )
    summary = accounting_summary(artifact)
    assert D(summary["net_pnl"]) == D(summary["gross_pnl"]) == D(summary["max_drawdown"]) == 0
    assert summary["fill_count"] == summary["order_count"] == 0
    assert summary["unavailable_signals"] == 10


def test_changed_artifact_refuses_report(engine, tmp_path):
    selected = preregister(config("test_backtest_report"), engine=engine, reported=False)
    path = run_backtest(selected, engine=engine, output_dir=tmp_path, reported=False)
    path.write_text(path.read_text() + " ")
    with pytest.raises(BacktestReportError, match="checksum"):
        generate_backtest_report(selected.run_id, engine=engine, output_root=tmp_path)


def test_changed_database_order_refuses_report(engine, connection, tmp_path):
    selected = preregister(config("test_backtest_report"), engine=engine, reported=False)
    run_backtest(selected, engine=engine, output_dir=tmp_path, reported=False)
    connection.execute(
        text("UPDATE orders SET status='CANCELLED' WHERE bt_run_id=:id"), {"id": selected.run_id}
    )
    with pytest.raises(BacktestReportError, match="orders differ"):
        generate_backtest_report(selected.run_id, engine=engine, output_root=tmp_path)
