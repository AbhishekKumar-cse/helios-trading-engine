"""Shared test fixtures.

`connection` gives every database test the same deal: a real PostgreSQL connection inside a
transaction that is **rolled back** afterwards, so tests never leave rows behind, and a skip
when no database is reachable (for example on CI).
"""

from collections.abc import Iterator

import pytest
from pydantic import ValidationError
from sqlalchemy import Connection

from helios.common import db
from helios.common.lineage import forget_git_state


@pytest.fixture
def connection() -> Iterator[Connection]:
    try:
        db.get_settings()
    except ValidationError:
        pytest.skip("database settings not configured (no .env / POSTGRES_* variables)")
    try:
        conn = db.get_engine().connect()
    except Exception as exc:  # noqa: BLE001 - any failure here means "no database"
        pytest.skip(f"database not reachable: {type(exc).__name__}")

    transaction = conn.begin()
    try:
        yield conn
    finally:
        transaction.rollback()
        conn.close()


@pytest.fixture(autouse=True)
def _fresh_git_state() -> None:
    """Forget the cached repository state before each test.

    `git_commit` and `git_is_dirty` are cached for speed (asking git costs most of a second
    on this filesystem). Tests create and change repositories, so each one starts from a
    clean slate.
    """
    forget_git_state()
