"""Real PostgreSQL trading constraints; all synthetic rows roll back."""

from decimal import Decimal

import pytest
from registry_sql import COMMIT, DEFINITION, HASH
from sqlalchemy import Connection, inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError

TABLES = {
    "strategies",
    "risk_limits",
    "orders",
    "fills",
    "positions_snapshot",
    "pnl_snapshots",
    "risk_events",
    "backtest_runs",
    "audit_events",
}


@pytest.fixture
def trading(connection: Connection) -> Connection:
    connection.execute(
        text(DEFINITION),
        dict(
            alpha_id="schema_test",
            version=1,
            provenance="human",
            family="H-HOURLY",
            horizon=1,
            commit=COMMIT,
        ),
    )
    connection.execute(
        text("""INSERT INTO strategies
        (strategy_id, alpha_id, alpha_version, params_json, code_commit)
        VALUES ('schema_strategy','schema_test',1,'{}',:commit)"""),
        {"commit": COMMIT},
    )
    connection.execute(
        text("""INSERT INTO risk_limits
        (limit_set_id,scope,version,limits,author,effective_from,hash)
        VALUES ('schema_limits','schema_strategy',1,'{}','test',now(),:hash)"""),
        {"hash": HASH},
    )
    instrument = connection.execute(
        text("""INSERT INTO instruments
        (symbol,base_asset,quote_asset,tick_size,lot_size,first_available_date)
        VALUES ('SCHEMAUSDT','SCHEMA','USDT',0.01,0.001,'2020-01-01')
        RETURNING instrument_id""")
    ).scalar_one()
    connection.info["test_instrument"] = instrument
    return connection


def insert_order(connection: Connection, **overrides: object) -> None:
    params = dict(
        id="order-test",
        client="client-test",
        instrument=connection.info["test_instrument"],
        side="BUY",
        qty="1",
        remaining="1",
        filled="0",
        price="100.01",
        simulated=True,
        hash=HASH,
    )
    params.update(overrides)
    connection.execute(
        text("""INSERT INTO orders (order_id,client_order_id,strategy_id,
        instrument_id,side,order_type,price,qty,remaining_qty,filled_qty,tif,status,
        ts_created,venue_id,is_simulated,limits_snapshot_hash)
        VALUES (:id,:client,'schema_strategy',:instrument,:side,'LIMIT',:price,:qty,
        :remaining,:filled,'GTC','NEW',1,'paper',:simulated,:hash)"""),
        params,
    )


def test_all_tables_visible(connection: Connection) -> None:
    assert TABLES <= set(inspect(connection).get_table_names())
    assert (
        connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        == "c11600000600"
    )


def test_order_and_fill_exact_values_and_references(trading: Connection) -> None:
    insert_order(trading)
    assert trading.execute(
        text("SELECT price FROM orders WHERE order_id='order-test'")
    ).scalar_one() == Decimal("100.01")
    trading.execute(
        text("""INSERT INTO fills
        (fill_id,order_id,instrument_id,side,price,qty,liquidity_flag,fee,ts_venue,ts_received,venue_id)
        VALUES ('fill-test','order-test',:instrument,'BUY',100.01,0.1,'TAKER',0.01,2,3,'paper')"""),
        {"instrument": trading.info["test_instrument"]},
    )
    assert (
        trading.execute(text("SELECT count(*) FROM fills WHERE fill_id='fill-test'")).scalar_one()
        == 1
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"qty": "0"},
        {"qty": "NaN"},
        {"qty": "Infinity"},
        {"remaining": "-1"},
        {"filled": "2"},
        {"price": "0"},
        {"price": None},
        {"side": "UNKNOWN"},
        {"simulated": False},
        {"hash": "f" * 64},
        {"instrument": -1},
    ],
)
def test_invalid_order_rejected(trading: Connection, overrides: dict[str, object]) -> None:
    with pytest.raises(DBAPIError):
        insert_order(trading, **overrides)


def test_client_id_is_idempotency_key(trading: Connection) -> None:
    insert_order(trading)
    with pytest.raises(IntegrityError):
        insert_order(trading, id="different-order")


def test_fill_cannot_change_order_side(trading: Connection) -> None:
    insert_order(trading)
    with pytest.raises(IntegrityError):
        trading.execute(
            text("""INSERT INTO fills
            (fill_id,order_id,instrument_id,side,price,qty,liquidity_flag,fee,ts_venue,ts_received,venue_id)
            VALUES ('bad-fill','order-test',:instrument,'SELL',100,0.1,'TAKER',0,1,2,'paper')"""),
            {"instrument": trading.info["test_instrument"]},
        )


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE risk_limits SET author='changed' WHERE limit_set_id='schema_limits'",
        "DELETE FROM risk_limits WHERE limit_set_id='schema_limits'",
        "UPDATE audit_events SET actor='changed' WHERE subject='synthetic'",
        "DELETE FROM audit_events WHERE subject='synthetic'",
    ],
)
def test_risk_versions_and_audit_are_insert_only(trading: Connection, statement: str) -> None:
    trading.execute(
        text(
            "INSERT INTO audit_events (ts,actor,action,subject) "
            "VALUES (1,'test','test','synthetic')"
        )
    )
    with pytest.raises(DBAPIError, match="insert-only"):
        trading.execute(text(statement))


def test_pnl_must_reconcile(trading: Connection) -> None:
    with pytest.raises(IntegrityError):
        trading.execute(
            text("""INSERT INTO pnl_snapshots
            (scope,ts,realised,unrealised,fees,total,gross_exposure,net_exposure,cash)
            VALUES ('test',1,10,2,1,12,0,0,100)""")
        )


def test_backtest_requires_real_preregistered_experiment(trading: Connection) -> None:
    with pytest.raises(IntegrityError):
        trading.execute(
            text("""INSERT INTO backtest_runs
            (bt_run_id,experiment_id,strategy_id,data_snapshot_id,code_commit,config_hash,
             seed,fill_model_ref,cost_model_ref)
            VALUES ('bad-backtest',-1,'schema_strategy','missing',
                :commit,:hash,0,'paper','fees_v1')"""),
            {"commit": COMMIT, "hash": HASH},
        )
