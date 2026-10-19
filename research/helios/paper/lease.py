"""Exclusive PostgreSQL ownership of a PAPER process or its crash recovery."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Connection, Engine, text


class PaperLease:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def check(self) -> None:
        # The retained transaction prevents transparent reconnection into a new
        # session that no longer owns the lock. Lost ownership must stop work.
        self.connection.execute(text("SELECT 1")).scalar_one()


@contextmanager
def paper_lease(engine: Engine, run_id: str) -> Iterator[PaperLease]:
    # Keep this connection checked out until the process exits. A dead connection
    # releases the session lock; another process must never cancel a live owner.
    params = dict(scope="helios_paper_owner:" + run_id)
    with engine.connect() as connection:
        acquired: bool = connection.execute(
            text("SELECT pg_try_advisory_lock(hashtextextended(:scope, 0))"), params
        ).scalar_one()
        if not acquired:
            raise ValueError("PAPER session already has an active owner")
        try:
            yield PaperLease(connection)
        finally:
            if not connection.invalidated:
                connection.execute(
                    text("SELECT pg_advisory_unlock(hashtextextended(:scope, 0))"), params
                )
