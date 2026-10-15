from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError
from test_paper_runtime import bar, definition, raw

from helios.alpha.definition import register_alpha_definition
from helios.common.config import config_hash
from helios.common.lineage import RunContext
from helios.data.binance import sha256_file
from helios.paper.config import smoke_config
from helios.paper.runtime import PaperRuntime
from helios.paper.store import PaperStore
from helios.sim.loss_risk import PostgresTripStore


@pytest.fixture
def paper_engine(connection):
    @contextmanager
    def transaction():
        with connection.begin_nested():
            yield connection

    engine = MagicMock(spec=Engine)
    engine.begin.side_effect = transaction
    engine.connect.side_effect = lambda: nullcontext(connection)
    connection.execute(
        text("""INSERT INTO instruments
        (symbol,base_asset,quote_asset,tick_size,lot_size,first_available_date)
        VALUES ('BTCUSDT','BTC','USDT',.01,.00001,'2020-01-01') ON CONFLICT(symbol) DO NOTHING""")
    )
    return engine


def test_incremental_paper_rows_survive_checkpoints_and_terminal_is_immutable(
    paper_engine, connection, tmp_path
):
    engine = paper_engine
    config = smoke_config("test_paper_store", "a" * 64).model_copy(
        update=dict(alpha_id="t_paper_fixture")
    )
    selected = definition(config)
    register_alpha_definition(connection, selected)
    context = RunContext(
        "a" * 40, False, config_hash(config), config.stream_id, 0, datetime.now(UTC)
    )
    store = PaperStore(engine, config, context)
    runtime = PaperRuntime(config, selected, context.code_commit, PostgresTripStore(engine))
    runtime.closed(bar(0, "100"))
    runtime.closed(bar(1, "101"))
    store.save(runtime)
    assert (
        connection.execute(
            text("SELECT count(*) FROM orders WHERE paper_run_id=:id"), dict(id=config.run_id)
        ).scalar_one()
        == 1
    )
    assert (
        connection.execute(
            text(
                "SELECT count(*) FROM fills f JOIN orders o USING(order_id) "
                "WHERE o.paper_run_id=:id"
            ),
            dict(id=config.run_id),
        ).scalar_one()
        == 0
    )
    from test_paper_runtime import BASE

    runtime.message(raw(2, closed=False, close="102"), (BASE + 120_000) * 1000 + 2_010_000)
    store.save(runtime)
    store.save(runtime)
    row = connection.execute(
        text(
            "SELECT o.status,o.is_simulated,o.bt_run_id,p.mode FROM orders o "
            "JOIN paper_runs p USING(paper_run_id) WHERE p.paper_run_id=:id"
        ),
        dict(id=config.run_id),
    ).one()
    assert tuple(row) == ("FILLED", True, None, "PAPER")
    assert (
        connection.execute(
            text(
                "SELECT count(*) FROM fills f JOIN orders o USING(order_id) "
                "WHERE o.paper_run_id=:id"
            ),
            dict(id=config.run_id),
        ).scalar_one()
        == 1
    )
    assert (
        connection.execute(
            text("SELECT count(*) FROM pnl_snapshots WHERE paper_run_id=:id"),
            dict(id=config.run_id),
        ).scalar_one()
        == 3
    )
    runtime.halt("bounded_test_end")
    assert runtime.store.is_tripped(config.run_id)
    artifact = tmp_path / "paper.json"
    artifact.write_text('{"is_synthetic":true}')
    store.finish(artifact, sha256_file(artifact), failed=False)
    with pytest.raises(DBAPIError, match="immutable"), connection.begin_nested():
        connection.execute(
            text("UPDATE paper_runs SET status='running' WHERE paper_run_id=:id"),
            dict(id=config.run_id),
        )
    with pytest.raises(ValueError, match="terminal"):
        store.save(runtime)


@pytest.mark.parametrize("disconnect", [False, True])
def test_runner_finalizes_success_or_retained_feed_failure(
    paper_engine, connection, tmp_path, monkeypatch, disconnect
):
    import asyncio

    from test_paper_runtime import BASE

    from helios.common import lineage
    from helios.data.resilient_klines import ResilientSummary
    from helios.paper import runner
    from helios.paper.runtime import PaperSafetyStop

    scope = "test_paper_failure" if disconnect else "test_paper_success"
    factory = smoke_config

    def config_factory(*args, **kwargs):
        return factory(*args, **kwargs).model_copy(update=dict(alpha_id="t_runner_fixture"))

    monkeypatch.setattr(runner, "smoke_config", config_factory)
    monkeypatch.setattr(runner, "git_is_dirty", lambda: False)
    monkeypatch.setattr(lineage, "git_is_dirty", lambda *_: False)
    selected = definition(config_factory(scope, "a" * 64))
    register_alpha_definition(connection, selected)

    async def feed(symbols, seconds, emit, event, **kwargs):
        emit(bar(0, "100"))
        emit(bar(1, "101"))
        if disconnect:
            event(dict(event="DISCONNECTED", received_time=bar(1).received_time + 1000))
        else:
            kwargs["on_message"](
                raw(2, closed=False, close="102"), (BASE + 120_000) * 1000 + 2_010_000
            )
        return ResilientSummary(
            started_time=0,
            finished_time=1,
            elapsed_seconds=0.1,
            connections=1,
            disconnects=0,
            received_updates=3,
            closed_bars={"BTCUSDT": 2},
        )

    monkeypatch.setattr(runner, "observe_resilient_klines", feed)
    invocation = runner.run_paper(scope, seconds=1, root=tmp_path, engine=paper_engine)
    if disconnect:
        with pytest.raises(PaperSafetyStop):
            asyncio.run(invocation)
    else:
        asyncio.run(invocation)
    row = connection.execute(
        text("SELECT status,artifact_sha256 FROM paper_runs WHERE paper_run_id=:id"), dict(id=scope)
    ).one()
    path = tmp_path / scope / "artifact.json"
    assert row.status == ("failed" if disconnect else "finished")
    assert row.artifact_sha256 == sha256_file(path)
    order = connection.execute(
        text("SELECT status FROM orders WHERE paper_run_id=:id"), dict(id=scope)
    ).scalar_one()
    assert order == ("CANCELLED" if disconnect else "FILLED")
    with pytest.raises(FileExistsError):
        asyncio.run(runner.run_paper(scope, seconds=1, root=tmp_path, engine=paper_engine))
