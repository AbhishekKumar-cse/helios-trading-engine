"""Pre-registering the question before looking at the answer (step 068).

An experiment says, in writing and before any run: *this is what we expect, and these are the
settings we will try*. Recording it afterwards proves nothing, because by then the answer is
known and the question can be bent to fit it.

Every result must name an experiment (migration 004), so there is no path from "measure fifty
variants" to "here is the one that worked" without the fifty being visible.

The status moves `planned -> running -> finished`, or `-> abandoned` at any point. Abandoning
is normal and is recorded rather than deleted: an idea that was dropped is information too.
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, text

from helios.registry.api import RegistryError

MIN_HYPOTHESIS = 10  # matches the database check


class ExperimentKind(StrEnum):
    """What sort of question is being asked. Matches the database check."""

    ALPHA = "alpha"
    ML = "ml"
    BACKTEST = "backtest"
    INFRASTRUCTURE = "infrastructure"
    OTHER = "other"


class ExperimentStatus(StrEnum):
    """Where the experiment stands."""

    PLANNED = "planned"
    RUNNING = "running"
    FINISHED = "finished"
    ABANDONED = "abandoned"


ALLOWED_MOVES: dict[ExperimentStatus, frozenset[ExperimentStatus]] = {
    ExperimentStatus.PLANNED: frozenset({ExperimentStatus.RUNNING, ExperimentStatus.ABANDONED}),
    ExperimentStatus.RUNNING: frozenset({ExperimentStatus.FINISHED, ExperimentStatus.ABANDONED}),
    ExperimentStatus.FINISHED: frozenset(),
    ExperimentStatus.ABANDONED: frozenset(),
}


class Experiment(BaseModel):
    """One pre-registered question."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    experiment_id: int = Field(ge=1)
    kind: ExperimentKind
    hypothesis: str = Field(min_length=MIN_HYPOTHESIS)
    params: dict[str, Any] = Field(default_factory=dict)
    author: str = Field(min_length=2)
    status: ExperimentStatus = ExperimentStatus.PLANNED
    code_commit: str | None = None
    config_hash: str | None = None
    snapshot_id: str | None = None
    notes: str | None = None
    pre_registered_at: datetime | None = None

    @property
    def is_open(self) -> bool:
        """Whether results may still be recorded against this experiment."""
        return self.status in (ExperimentStatus.PLANNED, ExperimentStatus.RUNNING)


INSERT = text("""
INSERT INTO experiments
    (kind, hypothesis, params, author, status, code_commit, config_hash, snapshot_id, notes)
VALUES
    (:kind, :hypothesis, CAST(:params AS jsonb), :author, :status,
     :code_commit, :config_hash, :snapshot_id, :notes)
RETURNING experiment_id, pre_registered_at
""")

SELECT = """
SELECT experiment_id, kind, hypothesis, params, author, status,
       code_commit, config_hash, snapshot_id, notes, pre_registered_at
FROM experiments
"""


def _to_experiment(row: Any) -> Experiment:
    return Experiment(
        experiment_id=row.experiment_id,
        kind=ExperimentKind(row.kind),
        hypothesis=row.hypothesis,
        params=row.params,
        author=row.author,
        status=ExperimentStatus(row.status),
        code_commit=row.code_commit,
        config_hash=row.config_hash,
        snapshot_id=row.snapshot_id,
        notes=row.notes,
        pre_registered_at=row.pre_registered_at,
    )


def register_experiment(
    connection: Connection,
    *,
    hypothesis: str,
    params: dict[str, Any] | None = None,
    kind: ExperimentKind = ExperimentKind.ALPHA,
    author: str,
    code_commit: str | None = None,
    config_hash: str | None = None,
    snapshot_id: str | None = None,
    notes: str | None = None,
) -> Experiment:
    """Write down the question and the settings, before any measurement is made."""
    if len(hypothesis.strip()) < MIN_HYPOTHESIS:
        raise RegistryError(
            f"write a real hypothesis of at least {MIN_HYPOTHESIS} characters "
            f"(what do you expect to find, and why?); got {hypothesis!r}"
        )

    try:
        row = connection.execute(
            INSERT,
            {
                "kind": kind.value,
                "hypothesis": hypothesis,
                "params": json.dumps(params or {}, sort_keys=True, default=str),
                "author": author,
                "status": ExperimentStatus.PLANNED.value,
                "code_commit": code_commit,
                "config_hash": config_hash,
                "snapshot_id": snapshot_id,
                "notes": notes,
            },
        ).one()
    except Exception as exc:  # noqa: BLE001 - turned into one clear registry error
        raise RegistryError(f"the experiment could not be registered: {exc}") from exc

    return Experiment(
        experiment_id=row.experiment_id,
        kind=kind,
        hypothesis=hypothesis,
        params=params or {},
        author=author,
        status=ExperimentStatus.PLANNED,
        code_commit=code_commit,
        config_hash=config_hash,
        snapshot_id=snapshot_id,
        notes=notes,
        pre_registered_at=row.pre_registered_at,
    )


def get_experiment(connection: Connection, experiment_id: int) -> Experiment:
    """One experiment by its id."""
    row = connection.execute(
        text(f"{SELECT} WHERE experiment_id = :experiment_id"),
        {"experiment_id": experiment_id},
    ).one_or_none()
    if row is None:
        raise RegistryError(
            f"experiment {experiment_id} is not registered; "
            "register the question before measuring anything"
        )
    return _to_experiment(row)


def require_open_experiment(connection: Connection, experiment_id: int) -> Experiment:
    """The experiment a result is about to be attached to, if it may still receive results."""
    experiment = get_experiment(connection, experiment_id)
    if not experiment.is_open:
        raise RegistryError(
            f"experiment {experiment_id} is {experiment.status}; "
            "register a new experiment for further runs"
        )
    return experiment


def set_status(connection: Connection, experiment_id: int, status: ExperimentStatus) -> Experiment:
    """Move an experiment along: planned -> running -> finished, or abandoned."""
    current = get_experiment(connection, experiment_id).status
    if status not in ALLOWED_MOVES[current]:
        allowed = ", ".join(sorted(ALLOWED_MOVES[current])) or "nothing"
        raise RegistryError(
            f"an experiment cannot go from {current} to {status}; allowed: {allowed}"
        )

    connection.execute(
        text("UPDATE experiments SET status = :status WHERE experiment_id = :experiment_id"),
        {"status": status.value, "experiment_id": experiment_id},
    )
    return get_experiment(connection, experiment_id)


def list_experiments(
    connection: Connection,
    *,
    kind: ExperimentKind | None = None,
    status: ExperimentStatus | None = None,
    author: str | None = None,
    limit: int = 100,
) -> list[Experiment]:
    """Registered experiments, newest first."""
    where = ["TRUE"]
    params: dict[str, Any] = {"limit": limit}
    for name, value in (
        ("kind", kind.value if kind else None),
        ("status", status.value if status else None),
        ("author", author),
    ):
        if value is not None:
            where.append(f"{name} = :{name}")
            params[name] = value

    rows = connection.execute(
        text(
            f"{SELECT} WHERE {' AND '.join(where)} "
            "ORDER BY pre_registered_at DESC, experiment_id DESC LIMIT :limit"
        ),
        params,
    ).all()
    return [_to_experiment(row) for row in rows]
