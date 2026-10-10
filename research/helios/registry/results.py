"""Recording what an evaluation produced (step 065).

A number without its origin is not evidence. Every result therefore carries four things, and
the model refuses to be built without them:

| Field | Answers |
|---|---|
| `code_commit` | which code produced it |
| `config_hash` | which settings |
| `snapshot_id` | which data, exactly (step 059) |
| `seed` | which random draw |

Since step 068 a result also names the **experiment** it answers, so no measurement exists
without a question that was written down before it.

`RunContext` (step 028) already collects all four, so `result_from_context()` is the normal
way to build a result and there is nothing to type twice.

Two further rules are enforced here rather than in the database, because they need to look at
several fields at once:

- a result may only be **PROMOTED** when every gate passed, the split is not TRAIN, and the
  working folder was clean;
- the gate outcomes must be named `G1` ... `G9`, so a typo cannot quietly invent a gate.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from helios.common.lineage import RunContext
from helios.registry.api import COMMIT, RegistryError
from helios.registry.experiments import require_open_experiment

GATE_NAME = re.compile(r"^G[1-9]$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class Split(StrEnum):
    """Which period a result was measured on (ADR-004)."""

    TRAIN = "train"
    VALID = "valid"
    TEST = "test"


class Status(StrEnum):
    """What was decided about a result."""

    EVALUATED = "EVALUATED"
    PROMOTED = "PROMOTED"
    REJECTED = "REJECTED"
    ARCHIVED = "ARCHIVED"


class AlphaResult(BaseModel):
    """One evaluation run of one alpha version."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    experiment_id: int = Field(ge=1)  # the pre-registered question this run answers (step 068)
    alpha_id: str
    version: int = Field(ge=1)
    split: Split
    snapshot_id: str = Field(min_length=8)
    gate_config_id: str = Field(min_length=3)

    # metrics, all net of costs
    sharpe: Decimal
    annual_return: Decimal
    turnover: Decimal = Field(ge=0)
    fitness: Decimal
    periods: int = Field(ge=1)
    max_drawdown: Decimal | None = Field(default=None, le=0)
    hit_rate: Decimal | None = Field(default=None, ge=0, le=1)
    cost_stress_sharpe: Decimal | None = None
    stability_positive_fraction: Decimal | None = Field(default=None, ge=0, le=1)
    runtime_seconds: Decimal | None = Field(default=None, ge=0)

    gate_results: dict[str, bool] = Field(min_length=1)
    status: Status = Status.EVALUATED

    # lineage: without these a result cannot be reproduced, so none of them has a default
    code_commit: str
    config_hash: str
    seed: int = Field(ge=0)
    dirty: bool

    created_at: datetime | None = None  # filled in by the database

    @field_validator("code_commit")
    @classmethod
    def _full_commit(cls, value: str) -> str:
        if not COMMIT.match(value):
            raise ValueError(f"code_commit must be a full 40-character git commit, got {value!r}")
        return value

    @field_validator("config_hash")
    @classmethod
    def _sha256(cls, value: str) -> str:
        if not SHA256.match(value):
            raise ValueError(f"config_hash must be a 64-character sha256, got {value!r}")
        return value

    @field_validator("gate_results")
    @classmethod
    def _known_gates(cls, value: dict[str, bool]) -> dict[str, bool]:
        unknown = sorted(name for name in value if not GATE_NAME.match(name))
        if unknown:
            raise ValueError(f"gate names must look like G1 ... G9; got {unknown}")
        return value

    @model_validator(mode="after")
    def _promotion_is_earned(self) -> Self:
        if self.status is not Status.PROMOTED:
            return self
        failed = sorted(name for name, passed in self.gate_results.items() if not passed)
        if failed:
            raise ValueError(f"cannot promote: {failed} did not pass")
        if self.split is Split.TRAIN:
            raise ValueError("cannot promote on the train split: gate G4 requires out-of-sample")
        if self.dirty:
            raise ValueError(
                "cannot promote a run made with uncommitted changes: it cannot be reproduced"
            )
        return self

    @property
    def passed_all_gates(self) -> bool:
        return all(self.gate_results.values())


def result_from_context(
    context: RunContext,
    *,
    experiment_id: int,
    alpha_id: str,
    version: int,
    split: Split,
    gate_config_id: str,
    sharpe: Decimal | str | float,
    annual_return: Decimal | str | float,
    turnover: Decimal | str | float,
    fitness: Decimal | str | float,
    periods: int,
    gate_results: dict[str, bool],
    **extra: Any,
) -> AlphaResult:
    """Build a result, taking all four lineage fields from the run context (step 028)."""
    return AlphaResult(
        experiment_id=experiment_id,
        alpha_id=alpha_id,
        version=version,
        split=split,
        snapshot_id=context.data_snapshot_id,
        gate_config_id=gate_config_id,
        sharpe=Decimal(str(sharpe)),
        annual_return=Decimal(str(annual_return)),
        turnover=Decimal(str(turnover)),
        fitness=Decimal(str(fitness)),
        periods=periods,
        gate_results=gate_results,
        code_commit=context.code_commit,
        config_hash=context.config_hash,
        seed=context.seed,
        dirty=context.dirty,
        **extra,
    )


INSERT = text("""
INSERT INTO alpha_results
    (run_id, experiment_id, alpha_id, version, split, snapshot_id, gate_config_id,
     sharpe, annual_return, turnover, fitness, max_drawdown, hit_rate,
     cost_stress_sharpe, stability_positive_fraction, periods, gate_results, status,
     code_commit, config_hash, seed, dirty, runtime_seconds)
VALUES
    (:run_id, :experiment_id, :alpha_id, :version, :split, :snapshot_id, :gate_config_id,
     :sharpe, :annual_return, :turnover, :fitness, :max_drawdown, :hit_rate,
     :cost_stress_sharpe, :stability_positive_fraction, :periods,
     CAST(:gate_results AS jsonb), :status,
     :code_commit, :config_hash, :seed, :dirty, :runtime_seconds)
RETURNING created_at
""")

SELECT = """
SELECT run_id, experiment_id, alpha_id, version, split, snapshot_id, gate_config_id,
       sharpe, annual_return, turnover, fitness, max_drawdown, hit_rate,
       cost_stress_sharpe, stability_positive_fraction, periods, gate_results, status,
       code_commit, config_hash, seed, dirty, runtime_seconds, created_at
FROM alpha_results
"""


def _to_result(row: Any) -> AlphaResult:
    return AlphaResult(
        run_id=row.run_id,
        experiment_id=row.experiment_id,
        alpha_id=row.alpha_id,
        version=row.version,
        split=Split(row.split),
        snapshot_id=row.snapshot_id,
        gate_config_id=row.gate_config_id,
        sharpe=row.sharpe,
        annual_return=row.annual_return,
        turnover=row.turnover,
        fitness=row.fitness,
        max_drawdown=row.max_drawdown,
        hit_rate=row.hit_rate,
        cost_stress_sharpe=row.cost_stress_sharpe,
        stability_positive_fraction=row.stability_positive_fraction,
        periods=row.periods,
        gate_results=row.gate_results,
        status=Status(row.status),
        code_commit=row.code_commit,
        config_hash=row.config_hash,
        seed=row.seed,
        dirty=row.dirty,
        runtime_seconds=row.runtime_seconds,
        created_at=row.created_at,
    )


def _broken_constraint(exc: IntegrityError) -> str | None:
    """The name of the constraint the database complained about, when it says."""
    diagnostics = getattr(exc.orig, "diag", None)
    return getattr(diagnostics, "constraint_name", None)


def record_result(connection: Connection, result: AlphaResult) -> AlphaResult:
    """Store one evaluation run. Results are never updated, only added.

    The experiment is checked first, so a run that belongs to no registered question is
    refused with an explanation rather than a foreign-key error.
    """
    require_open_experiment(connection, result.experiment_id)
    try:
        created_at: datetime = connection.execute(
            INSERT,
            {
                "run_id": result.run_id,
                "experiment_id": result.experiment_id,
                "alpha_id": result.alpha_id,
                "version": result.version,
                "split": result.split.value,
                "snapshot_id": result.snapshot_id,
                "gate_config_id": result.gate_config_id,
                "sharpe": result.sharpe,
                "annual_return": result.annual_return,
                "turnover": result.turnover,
                "fitness": result.fitness,
                "max_drawdown": result.max_drawdown,
                "hit_rate": result.hit_rate,
                "cost_stress_sharpe": result.cost_stress_sharpe,
                "stability_positive_fraction": result.stability_positive_fraction,
                "periods": result.periods,
                "gate_results": json.dumps(result.gate_results, sort_keys=True),
                "status": result.status.value,
                "code_commit": result.code_commit,
                "config_hash": result.config_hash,
                "seed": result.seed,
                "dirty": result.dirty,
                "runtime_seconds": result.runtime_seconds,
            },
        ).scalar_one()
    except IntegrityError as exc:
        # match on the constraint name, never on the message text: the message includes the
        # SQL statement, so a word like "snapshot_id" appears in it whatever went wrong
        broken = _broken_constraint(exc)
        if broken == "alpha_results_pkey":
            raise RegistryError(f"run {result.run_id} is already recorded") from exc
        if broken == "alpha_results_definition_fkey":
            raise RegistryError(
                f"{result.alpha_id} version {result.version} is not registered; "
                "register the definition before recording results for it"
            ) from exc
        if broken == "alpha_results_snapshot_id_fkey":
            raise RegistryError(
                f"data snapshot {result.snapshot_id} is unknown; "
                "build the bars so the snapshot is recorded first"
            ) from exc
        if broken == "alpha_results_experiment_fkey":
            raise RegistryError(
                f"experiment {result.experiment_id} is not registered; "
                "register the question before measuring anything"
            ) from exc
        if broken == "alpha_results_gate_config_id_fkey":
            raise RegistryError(f"gate configuration {result.gate_config_id} is unknown") from exc
        raise RegistryError(f"the database refused this result: {exc}") from exc

    return result.model_copy(update={"created_at": created_at})


def get_result(connection: Connection, run_id: str) -> AlphaResult:
    """One run by its id."""
    row = connection.execute(
        text(f"{SELECT} WHERE run_id = :run_id"), {"run_id": run_id}
    ).one_or_none()
    if row is None:
        raise RegistryError(f"run {run_id} is not recorded")
    return _to_result(row)


def list_results(
    connection: Connection,
    *,
    alpha_id: str | None = None,
    version: int | None = None,
    split: Split | None = None,
    status: Status | None = None,
    limit: int = 100,
) -> list[AlphaResult]:
    """Recorded runs, newest first."""
    where = ["TRUE"]
    params: dict[str, object] = {"limit": limit}
    for name, value, column in (
        ("alpha_id", alpha_id, "alpha_id"),
        ("version", version, "version"),
        ("split", split.value if split else None, "split"),
        ("status", status.value if status else None, "status"),
    ):
        if value is not None:
            where.append(f"{column} = :{name}")
            params[name] = value

    rows = connection.execute(
        text(f"{SELECT} WHERE {' AND '.join(where)} ORDER BY created_at DESC LIMIT :limit"),
        params,
    ).all()
    return [_to_result(row) for row in rows]
