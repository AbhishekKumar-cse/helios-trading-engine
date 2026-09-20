"""Registering and reading alpha definitions (step 064).

Research code never writes SQL by hand. It calls this module, which checks a definition
*before* it reaches the database and turns rows back into typed objects.

Two rules come from migration 003, where the tables are insert-only:

- an idea is **registered once per version**; registering the same version again is an error,
  not an update;
- changing anything about an idea means **a new version**, so the old one stays readable next
  to the results that were measured with it.

The pydantic model repeats several database constraints on purpose. The database is the last
line of defence and returns a blunt error; the model gives the researcher a clear message at
the point of the mistake.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from helios.common.lineage import git_commit
from helios.common.project_config import HorizonFamily

ALPHA_ID = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")


class RegistryError(Exception):
    """Raised when a definition is invalid, missing, or already registered."""


class Provenance(StrEnum):
    """Where an idea came from. Matches the database check."""

    HUMAN = "human"
    ML = "ml"
    GENETIC = "genetic"
    LITERATURE = "literature"


class AlphaDefinition(BaseModel):
    """One version of one alpha."""

    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=False)

    alpha_id: str
    version: int = Field(ge=1)
    name: str = Field(min_length=3, max_length=200)
    provenance: Provenance = Provenance.HUMAN
    spec: dict[str, Any] = Field(min_length=1)
    feature_set_version: str
    horizon_family: HorizonFamily
    horizon_periods: int = Field(ge=1)
    author: str = Field(min_length=2)
    code_commit: str = Field(default_factory=git_commit)
    created_at: datetime | None = None  # filled in by the database

    @field_validator("alpha_id")
    @classmethod
    def _readable_id(cls, value: str) -> str:
        if not ALPHA_ID.match(value):
            raise ValueError(
                f"alpha_id {value!r} must be lower-case letters, digits and underscores "
                "(3-64 characters), e.g. 'btc_hourly_momentum'"
            )
        return value

    @field_validator("code_commit")
    @classmethod
    def _full_commit(cls, value: str) -> str:
        if not COMMIT.match(value):
            raise ValueError(f"code_commit must be a full 40-character git commit, got {value!r}")
        return value


INSERT = text("""
INSERT INTO alpha_definitions
    (alpha_id, version, name, provenance, spec_json, feature_set_version,
     horizon_family, horizon_periods, author, code_commit)
VALUES
    (:alpha_id, :version, :name, :provenance, CAST(:spec AS jsonb), :feature_set_version,
     :horizon_family, :horizon_periods, :author, :code_commit)
RETURNING created_at
""")

SELECT = """
SELECT alpha_id, version, name, provenance, spec_json, feature_set_version,
       horizon_family, horizon_periods, author, code_commit, created_at
FROM alpha_definitions
"""


def _to_definition(row: Any) -> AlphaDefinition:
    return AlphaDefinition(
        alpha_id=row.alpha_id,
        version=row.version,
        name=row.name,
        provenance=Provenance(row.provenance),
        spec=row.spec_json,
        feature_set_version=row.feature_set_version,
        horizon_family=HorizonFamily(row.horizon_family),
        horizon_periods=row.horizon_periods,
        author=row.author,
        code_commit=row.code_commit,
        created_at=row.created_at,
    )


def register_definition(connection: Connection, definition: AlphaDefinition) -> AlphaDefinition:
    """Store one version of one alpha and return it with its stored creation time."""
    try:
        created_at = connection.execute(
            INSERT,
            {
                "alpha_id": definition.alpha_id,
                "version": definition.version,
                "name": definition.name,
                "provenance": definition.provenance.value,
                "spec": json.dumps(definition.spec, sort_keys=True),
                "feature_set_version": definition.feature_set_version,
                "horizon_family": definition.horizon_family.value,
                "horizon_periods": definition.horizon_periods,
                "author": definition.author,
                "code_commit": definition.code_commit,
            },
        ).scalar_one()
    except IntegrityError as exc:
        if "alpha_definitions_pkey" in str(exc):
            raise RegistryError(
                f"{definition.alpha_id} version {definition.version} is already registered; "
                "a change to an idea is a new version, never an edit of the old one"
            ) from exc
        raise RegistryError(f"the database refused this definition: {exc}") from exc

    return definition.model_copy(update={"created_at": created_at})


def next_version(connection: Connection, alpha_id: str) -> int:
    """The version number to use for the next registration of this alpha (1 if it is new)."""
    highest = connection.execute(
        text("SELECT max(version) FROM alpha_definitions WHERE alpha_id = :alpha_id"),
        {"alpha_id": alpha_id},
    ).scalar_one()
    return 1 if highest is None else int(highest) + 1


def get_alpha(connection: Connection, alpha_id: str, version: int | None = None) -> AlphaDefinition:
    """One alpha: the given version, or the newest one when no version is asked for."""
    if version is None:
        row = connection.execute(
            text(f"{SELECT} WHERE alpha_id = :alpha_id ORDER BY version DESC LIMIT 1"),
            {"alpha_id": alpha_id},
        ).one_or_none()
    else:
        row = connection.execute(
            text(f"{SELECT} WHERE alpha_id = :alpha_id AND version = :version"),
            {"alpha_id": alpha_id, "version": version},
        ).one_or_none()

    if row is None:
        wanted = alpha_id if version is None else f"{alpha_id} version {version}"
        raise RegistryError(f"{wanted} is not registered")
    return _to_definition(row)


def list_alphas(
    connection: Connection,
    *,
    latest_only: bool = True,
    author: str | None = None,
    horizon_family: HorizonFamily | None = None,
) -> list[AlphaDefinition]:
    """Registered alphas, newest first.

    `latest_only` keeps one row per alpha (its highest version), which is usually what a
    researcher wants; pass False to see the whole history of every idea.
    """
    where = ["TRUE"]
    params: dict[str, object] = {}
    if author is not None:
        where.append("author = :author")
        params["author"] = author
    if horizon_family is not None:
        where.append("horizon_family = :family")
        params["family"] = horizon_family.value

    conditions = " AND ".join(where)
    if latest_only:
        query = f"""
            SELECT DISTINCT ON (alpha_id) * FROM ({SELECT} WHERE {conditions}) AS d
            ORDER BY alpha_id, version DESC
        """
    else:
        query = f"{SELECT} WHERE {conditions}"

    rows = connection.execute(
        text(f"SELECT * FROM ({query}) AS listed ORDER BY created_at DESC, alpha_id, version DESC"),
        params,
    ).all()
    return [_to_definition(row) for row in rows]


def count_versions(connection: Connection, alpha_id: str) -> int:
    """How many versions of this alpha exist."""
    return int(
        connection.execute(
            text("SELECT count(*) FROM alpha_definitions WHERE alpha_id = :alpha_id"),
            {"alpha_id": alpha_id},
        ).scalar_one()
    )
