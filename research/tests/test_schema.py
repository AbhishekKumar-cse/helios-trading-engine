"""The rules in migration 001 are enforced by the database itself (step 057).

Every test runs inside a transaction that is rolled back, so the database is left untouched.
They skip when PostgreSQL is not available (for example on CI).

Why test the database and not just the code: a rule written in Python only holds for code
that remembers to call it. A CHECK constraint holds for every insert, from any script, any
teammate and any tool, including someone typing SQL into Adminer.
"""

from collections.abc import Iterator
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from helios.common import db

pytestmark = pytest.mark.usefixtures("connection")

INSTRUMENT = """
INSERT INTO instruments
    (symbol, base_asset, quote_asset, tick_size, lot_size, first_available_date)
VALUES (:symbol, 'BTC', 'USDT', :tick, :lot, DATE '2017-08-17')
"""

SNAPSHOT = """
INSERT INTO data_snapshots
    (snapshot_id, source, interval, symbols, first_open_time, last_open_time,
     file_count, row_count, total_bytes, code_commit)
VALUES (:id, 'binance', '1h', '["BTCUSDT"]'::jsonb, :first, :last, :files, 100, 1000, 'abc123')
"""

EXPERIMENT = """
INSERT INTO experiments (kind, hypothesis, author, status)
VALUES (:kind, :hypothesis, 'abhishek', :status)
"""


@pytest.fixture
def connection() -> Iterator[Connection]:
    try:
        db.get_settings()
    except ValidationError:
        pytest.skip("database settings not configured (no .env / POSTGRES_* variables)")
    engine = db.get_engine()
    try:
        conn = engine.connect()
    except Exception as exc:  # noqa: BLE001 - any connection failure means "no database here"
        pytest.skip(f"database not reachable: {type(exc).__name__}")
    transaction = conn.begin()
    try:
        yield conn
    finally:
        transaction.rollback()  # nothing these tests write is kept
        conn.close()


def test_the_three_tables_exist(connection: Connection) -> None:
    found = connection.execute(
        text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
    ).scalars()
    assert {"instruments", "data_snapshots", "experiments"} <= set(found)


# ---------------------------------------------------------------- instruments


def test_a_valid_instrument_is_accepted(connection: Connection) -> None:
    connection.execute(text(INSTRUMENT), {"symbol": "BTCUSDT", "tick": "0.01", "lot": "0.00001"})
    count = connection.execute(
        text("SELECT count(*) FROM instruments WHERE symbol = 'BTCUSDT'")
    ).scalar_one()
    assert count == 1


def test_lower_case_symbol_is_refused(connection: Connection) -> None:
    with pytest.raises(IntegrityError, match="instruments_symbol_upper"):
        connection.execute(
            text(INSTRUMENT), {"symbol": "btcusdt", "tick": "0.01", "lot": "0.00001"}
        )


@pytest.mark.parametrize("value", ["0", "-0.01"])
def test_tick_size_must_be_positive(connection: Connection, value: str) -> None:
    with pytest.raises(IntegrityError, match="instruments_tick_size_positive"):
        connection.execute(text(INSTRUMENT), {"symbol": "ETHUSDT", "tick": value, "lot": "1"})


def test_the_same_symbol_cannot_be_added_twice(connection: Connection) -> None:
    params = {"symbol": "SOLUSDT", "tick": "0.01", "lot": "0.001"}
    connection.execute(text(INSTRUMENT), params)
    with pytest.raises(IntegrityError, match="instruments_symbol_key"):
        connection.execute(text(INSTRUMENT), params)


def test_prices_keep_their_exact_decimals(connection: Connection) -> None:
    """Stored as NUMERIC, not floating point, so a tick size comes back exactly as written.

    With a float, 0.1 + 0.2 is 0.30000000000000004; prices and sizes must never drift.
    """
    connection.execute(text(INSTRUMENT), {"symbol": "XRPUSDT", "tick": "0.00000001", "lot": "0.1"})
    tick = connection.execute(
        text("SELECT tick_size FROM instruments WHERE symbol = 'XRPUSDT'")
    ).scalar_one()
    assert isinstance(tick, Decimal)  # not a float
    assert tick == Decimal("0.00000001")
    assert (
        Decimal("0.1") + Decimal("0.2")
        == connection.execute(text("SELECT 0.1::numeric + 0.2::numeric")).scalar_one()
    )


# ---------------------------------------------------------------- data_snapshots


def test_a_snapshot_is_accepted(connection: Connection) -> None:
    connection.execute(text(SNAPSHOT), {"id": "sha-1", "first": 1, "last": 2, "files": 3})
    assert connection.execute(text("SELECT count(*) FROM data_snapshots")).scalar_one() == 1


def test_a_snapshot_cannot_end_before_it_starts(connection: Connection) -> None:
    with pytest.raises(IntegrityError, match="data_snapshots_range_ordered"):
        connection.execute(text(SNAPSHOT), {"id": "sha-2", "first": 100, "last": 99, "files": 1})


def test_a_snapshot_must_cover_at_least_one_file(connection: Connection) -> None:
    with pytest.raises(IntegrityError, match="data_snapshots_files_positive"):
        connection.execute(text(SNAPSHOT), {"id": "sha-3", "first": 1, "last": 2, "files": 0})


# ---------------------------------------------------------------- experiments


def test_an_experiment_is_accepted(connection: Connection) -> None:
    connection.execute(
        text(EXPERIMENT),
        {
            "kind": "alpha",
            "hypothesis": "hourly momentum on BTC beats holding it, after costs",
            "status": "planned",
        },
    )
    assert connection.execute(text("SELECT count(*) FROM experiments")).scalar_one() == 1


def test_an_unknown_kind_is_refused(connection: Connection) -> None:
    with pytest.raises(IntegrityError, match="experiments_kind_known"):
        connection.execute(
            text(EXPERIMENT),
            {"kind": "magic", "hypothesis": "something long enough", "status": "planned"},
        )


def test_an_unknown_status_is_refused(connection: Connection) -> None:
    with pytest.raises(IntegrityError, match="experiments_status_known"):
        connection.execute(
            text(EXPERIMENT),
            {"kind": "alpha", "hypothesis": "something long enough", "status": "great"},
        )


def test_an_empty_hypothesis_is_refused(connection: Connection) -> None:
    """A question has to be written down before the answer is known, or it proves nothing."""
    with pytest.raises(IntegrityError, match="experiments_hypothesis_not_empty"):
        connection.execute(
            text(EXPERIMENT), {"kind": "alpha", "hypothesis": "too short", "status": "planned"}
        )


def test_an_experiment_cannot_point_at_a_missing_snapshot(connection: Connection) -> None:
    with pytest.raises((IntegrityError, DBAPIError), match="snapshot"):
        connection.execute(
            text(
                "INSERT INTO experiments (kind, hypothesis, author, snapshot_id) "
                "VALUES ('alpha', 'a hypothesis long enough to pass', 'abhishek', 'no-such-id')"
            )
        )


def test_a_used_snapshot_cannot_be_deleted(connection: Connection) -> None:
    """Results must stay explainable: the data they used cannot vanish underneath them."""
    connection.execute(text(SNAPSHOT), {"id": "sha-9", "first": 1, "last": 2, "files": 1})
    connection.execute(
        text(
            "INSERT INTO experiments (kind, hypothesis, author, snapshot_id) "
            "VALUES ('alpha', 'a hypothesis long enough to pass', 'abhishek', 'sha-9')"
        )
    )
    with pytest.raises(IntegrityError, match="foreign key|violates"):
        connection.execute(text("DELETE FROM data_snapshots WHERE snapshot_id = 'sha-9'"))
