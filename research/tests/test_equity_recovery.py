"""Synthetic crash/kill injection against the real, rolled-back PostgreSQL store."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlalchemy.exc import PendingRollbackError
from test_equity_paper import candle, quote, runtime
from test_paper_store import paper_engine as _paper_engine

from helios.alpha.definition import register_alpha_definition
from helios.common.config import config_hash
from helios.common.db import get_engine
from helios.common.lineage import RunContext
from helios.dashboard.control import kill_paper
from helios.data.equities import sha256, write_json
from helios.equities import recovery
from helios.equities.paper_config import equity_paper_config
from helios.paper.lease import paper_lease
from helios.paper.runtime import PaperRuntime, PaperSafetyStop
from helios.paper.store import PaperStore
from helios.sim.loss_risk import PostgresTripStore, tripped

paper_engine = pytest.fixture(_paper_engine.__wrapped__)


@pytest.fixture
def session(paper_engine, connection, tmp_path):
    folder = tmp_path / "nse_recovery_fixture"
    folder.mkdir()
    identity = folder / "session.json"
    write_json(
        identity,
        dict(
            version="nse_paper_session_v2",
            ownership="postgres_session_advisory_lock_v1",
            run_id=folder.name,
            code_commit="b" * 40,
            symbol="EXAMPLE",
            is_synthetic=True,
        ),
    )
    selected = runtime().definition
    config = equity_paper_config(folder.name, sha256(identity), selected.alpha_id, "EXAMPLE")
    connection.execute(
        text("""INSERT INTO instruments
        (symbol,venue,base_asset,quote_asset,tick_size,lot_size,first_available_date)
        VALUES ('EXAMPLE','nse_cash','EXAMPLE','INR',.05,1,'2025-01-01')
        ON CONFLICT(symbol) DO NOTHING""")
    )
    register_alpha_definition(connection, selected)
    context = RunContext(
        "b" * 40, False, config_hash(config), config.stream_id, 0, datetime.now(UTC)
    )
    store = PaperStore(paper_engine, config, context)
    live = PaperRuntime(config, selected, context.code_commit, PostgresTripStore(paper_engine))
    for offset in range(4):
        live.closed(candle(offset))
    store.save(live)
    return live, store, tmp_path


def test_restart_cancels_pending_and_keeps_terminal_evidence(session, paper_engine, connection):
    live, store, root = session
    artifact = recovery.recover_equity_paper(
        live.config.run_id, "synthetic_operator", root=root, engine=paper_engine
    )
    evidence = json.loads(artifact.read_text())
    assert evidence["reconciliation"]["status"] == "RECONCILED"
    assert evidence["reconciliation"]["fills"] == 0
    assert Decimal(evidence["reconciliation"]["cash"]) == Decimal(100000)
    assert len(evidence["cancelled_simulated_intents"]) == 1
    assert tripped(connection, live.config.run_id)
    assert (
        connection.execute(
            text("SELECT status FROM orders WHERE paper_run_id=:id"), dict(id=live.config.run_id)
        ).scalar_one()
        == "CANCELLED"
    )
    assert connection.execute(
        text("SELECT artifact_sha256 FROM paper_runs WHERE paper_run_id=:id"),
        dict(id=live.config.run_id),
    ).scalar_one() == sha256(artifact)
    with pytest.raises(ValueError, match="terminal"):
        store.save(live)
    with pytest.raises(ValueError, match="running"):
        recovery.recover_equity_paper(
            live.config.run_id, "synthetic_operator", root=root, engine=paper_engine
        )


def test_restart_reconstructs_nonflat_inventory_without_an_exit_fill(
    session,
    paper_engine,
    connection,
):
    live, store, root = session
    stamp = candle(3).event_time + 2_000_000
    live.message(quote(stamp), stamp + 10_000)
    store.save(live)
    position = live.ledger.position(live.config.symbol)
    assert position.quantity > 0
    artifact = recovery.recover_equity_paper(
        live.config.run_id, "synthetic_operator", root=root, engine=paper_engine
    )
    result = json.loads(artifact.read_text())["reconciliation"]
    assert result["status"] == "RECONCILED"
    assert result["position"] == position.model_dump(mode="json")
    assert Decimal(result["cash"]) == live.snapshots[-1].cash
    assert result["fills"] == 1 and not result["automatic_resume"]
    assert (
        connection.execute(
            text("SELECT count(*) FROM fills JOIN orders USING(order_id) WHERE paper_run_id=:id"),
            dict(id=live.config.run_id),
        ).scalar_one()
        == 1
    )


def test_recovery_mismatch_is_retained_and_still_halts(session, paper_engine):
    live, _, root = session
    with patch.object(recovery, "reconcile_records", side_effect=ValueError("injected mismatch")):
        artifact = recovery.recover_equity_paper(
            live.config.run_id, "synthetic_operator", root=root, engine=paper_engine
        )
    assert json.loads(artifact.read_text())["reconciliation"]["status"] == "MISMATCH"


def test_recovery_cannot_cancel_a_live_owner(session, paper_engine, connection):
    live, _, root = session
    with paper_lease(get_engine(), live.config.run_id):
        with pytest.raises(ValueError, match="active owner"):
            recovery.recover_equity_paper(
                live.config.run_id, "synthetic_operator", root=root, engine=paper_engine
            )
    assert not tripped(connection, live.config.run_id)
    assert not list((root / live.config.run_id).glob("recovery_*.json"))


def test_changed_session_identity_cannot_reconcile_another_stream(
    session,
    paper_engine,
    connection,
):
    live, _, root = session
    identity = root / live.config.run_id / "session.json"
    identity.write_text(identity.read_text() + "\n")
    with pytest.raises(ValueError, match="lineage"):
        recovery.recover_equity_paper(
            live.config.run_id, "synthetic_operator", root=root, engine=paper_engine
        )
    assert not tripped(connection, live.config.run_id)


@pytest.mark.parametrize(
    "table,column",
    [
        ("orders", "filled_qty"),
        ("pnl_snapshots", "cash"),
        ("positions_snapshot", "net_qty"),
        ("fills", "qty"),
    ],
)
def test_recovery_detects_corrupted_durable_accounting(
    session,
    paper_engine,
    connection,
    table,
    column,
):
    live, store, root = session
    stamp = candle(3).event_time + 2_000_000
    live.message(quote(stamp), stamp + 10_000)
    store.save(live)
    # Alter only the returned DB evidence, never append-only stored records.
    execute = connection.execute

    def altered(statement, *args, **kwargs):
        result = execute(statement, *args, **kwargs)
        sql = str(statement)
        wanted = {
            "orders": "SELECT o.*",
            "fills": "SELECT f.*",
            "pnl_snapshots": "SELECT * FROM pnl_snapshots",
            "positions_snapshot": "SELECT p.*",
        }[table]
        if not sql.startswith(wanted):
            return result
        from unittest.mock import MagicMock

        rows = [dict(row) for row in result.mappings()]
        rows[-1][column] += Decimal(1)
        changed = MagicMock()
        changed.mappings.return_value = rows
        return changed

    with patch.object(connection, "execute", side_effect=altered):
        artifact = recovery.recover_equity_paper(
            live.config.run_id, "synthetic_operator", root=root, engine=paper_engine
        )
    assert json.loads(artifact.read_text())["reconciliation"]["status"] == "MISMATCH"


def test_recovery_audit_failure_rolls_back_halt_and_cancellation(
    session,
    paper_engine,
    connection,
):
    live, _, root = session
    execute = connection.execute

    def fail(statement, *args, **kwargs):
        if "PAPER_CRASH_RECOVERY" in str(statement):
            raise RuntimeError("injected audit failure")
        return execute(statement, *args, **kwargs)

    with patch.object(connection, "execute", side_effect=fail):
        with pytest.raises(RuntimeError, match="injected"):
            recovery.recover_equity_paper(
                live.config.run_id, "synthetic_operator", root=root, engine=paper_engine
            )
    assert not tripped(connection, live.config.run_id)
    assert (
        connection.execute(
            text("SELECT status FROM orders WHERE paper_run_id=:id"), dict(id=live.config.run_id)
        ).scalar_one()
        == "ACK"
    )
    assert (
        connection.execute(
            text("SELECT status FROM paper_runs WHERE paper_run_id=:id"),
            dict(id=live.config.run_id),
        ).scalar_one()
        == "running"
    )


def test_equity_dashboard_kill_works_without_a_subsequent_quote(
    session,
    paper_engine,
    connection,
):
    live, store, _ = session
    pending = live.oms.snapshot()[0].request
    assert kill_paper(
        live.config.run_id, "synthetic_operator", "Synthetic kill test", engine=paper_engine
    )
    with pytest.raises(PaperSafetyStop, match="operator_kill"):
        live.check_health(live.clock + 1, started_at=candle(0).received_time)
    store.save(live)
    assert live.oms.snapshot()[0].state.value == "CANCELLED"
    assert live.risk.check(pending).reason.value == "HALTED"
    assert not any(r.fill for r in live.reports)
    assert (
        connection.execute(
            text(
                "SELECT count(*) FROM audit_events "
                "WHERE subject=:id AND action='PAPER_KILL_REQUEST'"
            ),
            dict(id=live.config.run_id),
        ).scalar_one()
        == 1
    )


def test_silent_feed_cancels_even_without_quotes():
    live = runtime()
    for offset in range(4):
        live.closed(candle(offset))
    with pytest.raises(PaperSafetyStop, match="feed_silence"):
        live.check_health(live.clock + 5_000_001, started_at=candle(0).received_time)
    assert live.oms.snapshot()[0].state.value == "CANCELLED"
    assert not any(r.fill for r in live.reports)


def test_startup_waits_for_a_fresh_minute_but_is_bounded():
    live = runtime()
    start = candle(0).received_time
    live.check_health(start + 65_000_000, started_at=start)
    with pytest.raises(PaperSafetyStop, match="feed_silence"):
        live.check_health(start + 65_000_001, started_at=start)


def test_lease_refuses_second_postgres_connection_and_releases_after_exit(connection):
    # Actual separate database sessions, no writes or committed fixture data.
    engine = get_engine()
    with paper_lease(engine, "synthetic_lease_test"):
        with pytest.raises(ValueError, match="active owner"):
            with paper_lease(engine, "synthetic_lease_test"):
                pytest.fail("two processes owned one scope")
    with paper_lease(engine, "synthetic_lease_test"):
        pass


def test_lost_owner_connection_cannot_silently_reconnect(connection):
    engine = get_engine()
    with paper_lease(engine, "synthetic_lost_lease") as lease:
        lease.check()
        lease.connection.invalidate()  # Lose this owned DB session, not another process's session.
        with pytest.raises(PendingRollbackError):
            lease.check()
        with paper_lease(engine, "synthetic_lost_lease"):
            pass
