"""Guarding the TEST period (step 067).

ADR-004 allows the TEST period to be used **at most twice per alpha version**. The reason is
simple: every look at the final hold-out teaches you something about it, and after enough
looks you are tuning on it without meaning to. The number then says more about how many
attempts were made than about the idea.

A rule that lives only in a document gets forgotten at 2 a.m. before a deadline. So every
use is written down here, and the **third** attempt is refused.

Each access records who did it, when, on which data snapshot, and why. "Why" is not
decoration: an access with a stated purpose is a decision, while an unexplained one is a
habit.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, text

from helios.registry.api import RegistryError
from helios.registry.results import AlphaResult, Split, record_result

MAX_TEST_ACCESSES = 2  # ADR-004
MIN_PURPOSE = 10  # matches the database check


class TestSetLimitReached(RegistryError):
    """Raised when an alpha version has already used its two TEST accesses."""


class TestSetAccess(BaseModel):
    """One recorded use of the TEST period."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    access_id: int
    alpha_id: str
    version: int
    snapshot_id: str
    run_id: str | None
    actor: str = Field(min_length=2)
    purpose: str = Field(min_length=MIN_PURPOSE)
    accessed_at: datetime


INSERT = text("""
INSERT INTO test_set_access (alpha_id, version, snapshot_id, run_id, actor, purpose)
VALUES (:alpha_id, :version, :snapshot_id, :run_id, :actor, :purpose)
RETURNING access_id, accessed_at
""")

SELECT = """
SELECT access_id, alpha_id, version, snapshot_id, run_id, actor, purpose, accessed_at
FROM test_set_access
"""


def count_test_accesses(connection: Connection, alpha_id: str, version: int) -> int:
    """How many times this alpha version has already used the TEST period."""
    return int(
        connection.execute(
            text(
                "SELECT count(*) FROM test_set_access "
                "WHERE alpha_id = :alpha_id AND version = :version"
            ),
            {"alpha_id": alpha_id, "version": version},
        ).scalar_one()
    )


def remaining_test_accesses(connection: Connection, alpha_id: str, version: int) -> int:
    """How many uses of the TEST period are left for this alpha version."""
    return max(0, MAX_TEST_ACCESSES - count_test_accesses(connection, alpha_id, version))


def ensure_test_budget(connection: Connection, alpha_id: str, version: int) -> int:
    """Refuse if this alpha version has no TEST accesses left; return how many are used.

    The advisory lock holds until the transaction ends, so two runs started at the same
    moment cannot both read "one access used" and slip past the limit together.
    """
    connection.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"test_set_access:{alpha_id}:{version}"},
    )
    used = count_test_accesses(connection, alpha_id, version)
    if used >= MAX_TEST_ACCESSES:
        raise TestSetLimitReached(
            f"{alpha_id} version {version} has already used the TEST period "
            f"{used} times, and ADR-004 allows {MAX_TEST_ACCESSES}. "
            "Work on the validation period, or register a new version of the idea."
        )
    return used


def record_test_access(
    connection: Connection,
    *,
    alpha_id: str,
    version: int,
    snapshot_id: str,
    actor: str,
    purpose: str,
    run_id: str | None = None,
) -> TestSetAccess:
    """Write down one use of the TEST period, or refuse it if the limit is already reached."""
    if len(purpose.strip()) < MIN_PURPOSE:
        raise RegistryError(
            f"say why the TEST period is being used (at least {MIN_PURPOSE} characters); "
            f"got {purpose!r}"
        )

    ensure_test_budget(connection, alpha_id, version)

    try:
        row = connection.execute(
            INSERT,
            {
                "alpha_id": alpha_id,
                "version": version,
                "snapshot_id": snapshot_id,
                "run_id": run_id,
                "actor": actor,
                "purpose": purpose,
            },
        ).one()
    except Exception as exc:  # noqa: BLE001 - turned into one clear registry error
        raise RegistryError(f"the TEST access could not be recorded: {exc}") from exc

    return TestSetAccess(
        access_id=row.access_id,
        alpha_id=alpha_id,
        version=version,
        snapshot_id=snapshot_id,
        run_id=run_id,
        actor=actor,
        purpose=purpose,
        accessed_at=row.accessed_at,
    )


def list_test_accesses(
    connection: Connection, alpha_id: str | None = None, version: int | None = None
) -> list[TestSetAccess]:
    """Recorded TEST uses, oldest first."""
    where = ["TRUE"]
    params: dict[str, Any] = {}
    if alpha_id is not None:
        where.append("alpha_id = :alpha_id")
        params["alpha_id"] = alpha_id
    if version is not None:
        where.append("version = :version")
        params["version"] = version

    rows = connection.execute(
        text(f"{SELECT} WHERE {' AND '.join(where)} ORDER BY accessed_at, access_id"), params
    ).all()
    return [
        TestSetAccess(
            access_id=row.access_id,
            alpha_id=row.alpha_id,
            version=row.version,
            snapshot_id=row.snapshot_id,
            run_id=row.run_id,
            actor=row.actor,
            purpose=row.purpose,
            accessed_at=row.accessed_at,
        )
        for row in rows
    ]


def record_test_result(
    connection: Connection, result: AlphaResult, *, actor: str, purpose: str
) -> tuple[AlphaResult, TestSetAccess]:
    """Record a result measured on the TEST period, together with the access that allowed it.

    The budget is checked **before anything is written**, and the result and the access are
    written in the same transaction, so a run over the limit stores neither. There is no way
    to see the TEST numbers first and then decide whether to admit having looked.

    (The result is inserted before the access row only because the access points at the run
    by its id; the decision to allow it happened before either.)
    """
    if result.split is not Split.TEST:
        raise RegistryError(
            f"record_test_result is only for the TEST split; this result is {result.split}. "
            "Use record_result for train and validation runs."
        )

    ensure_test_budget(connection, result.alpha_id, result.version)
    stored = record_result(connection, result)
    access = record_test_access(
        connection,
        alpha_id=result.alpha_id,
        version=result.version,
        snapshot_id=result.snapshot_id,
        actor=actor,
        purpose=purpose,
        run_id=stored.run_id,
    )
    return stored, access
