"""YAML-facing alpha definitions (step 085).

The registry record is deliberately unchanged: expression/model reference and params
live in spec_json. QUANT maps to its existing 'human' provenance and ML to 'ml'.
Loading validates the definition only; parsing/evaluating expressions is step 086 onward.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import ConfigDict, Field, JsonValue, StrictInt, field_validator, model_validator
from sqlalchemy import Connection

from helios.common.config import HeliosConfig, load_config
from helios.common.lineage import git_commit
from helios.common.project_config import HorizonFamily
from helios.registry.api import ALPHA_ID, COMMIT, Provenance, register_definition
from helios.registry.api import AlphaDefinition as RegistryDefinition


class AlphaProvenance(StrEnum):
    """The two alpha-generation routes in the semester plan."""

    QUANT = "QUANT"
    ML = "ML"


class AlphaDefinition(HeliosConfig):
    """One immutable version of an idea, with no measured result or user-supplied state."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    alpha_id: str
    version: StrictInt = Field(ge=1)
    name: str = Field(min_length=3, max_length=200)
    provenance: AlphaProvenance
    feature_set_version: str = Field(min_length=1)
    horizon_family: HorizonFamily
    horizon_periods: StrictInt = Field(ge=1)
    params: dict[str, JsonValue] = Field(default_factory=dict)
    expression: str | None = Field(default=None, min_length=1)
    model_ref: str | None = Field(default=None, min_length=1)
    author: str = Field(min_length=2)
    code_commit: str = Field(default_factory=git_commit)

    @field_validator("alpha_id")
    @classmethod
    def _readable_id(cls, value: str) -> str:
        if not ALPHA_ID.fullmatch(value):
            raise ValueError("alpha_id must be 3-64 lowercase letters, digits or underscores")
        return value

    @field_validator("code_commit")
    @classmethod
    def _full_commit(cls, value: str) -> str:
        if not COMMIT.fullmatch(value):
            raise ValueError("code_commit must be a full 40-character git commit")
        return value

    @field_validator("params")
    @classmethod
    def _finite_json(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        # Includes nested values: JSONB cannot preserve NaN or Infinity.
        try:
            json.dumps(value, allow_nan=False)
        except ValueError as exc:
            raise ValueError("params must contain only finite JSON values") from exc
        return value

    @model_validator(mode="after")
    def _one_formula_or_model(self) -> Self:
        if (self.expression is None) == (self.model_ref is None):
            raise ValueError("provide exactly one expression or model_ref")
        if self.provenance is AlphaProvenance.QUANT and self.expression is None:
            raise ValueError("QUANT definitions require an expression")
        return self

    def to_registry(self) -> RegistryDefinition:
        """Adapt without changing the insert-only registry schema or older definitions."""
        spec = {"params": self.model_dump(mode="json")["params"]}
        if self.expression is not None:
            spec["expression"] = self.expression
        else:
            spec["model_ref"] = self.model_ref
        return RegistryDefinition(
            alpha_id=self.alpha_id,
            version=self.version,
            name=self.name,
            provenance=Provenance.HUMAN
            if self.provenance is AlphaProvenance.QUANT
            else Provenance.ML,
            spec=spec,
            feature_set_version=self.feature_set_version,
            horizon_family=self.horizon_family,
            horizon_periods=self.horizon_periods,
            author=self.author,
            code_commit=self.code_commit,
        )


def load_alpha_definition(path: str | Path) -> AlphaDefinition:
    """Safely load YAML; no expression evaluation, data access or registry write occurs."""
    return load_config(path, AlphaDefinition)


def register_alpha_definition(
    connection: Connection, definition: AlphaDefinition
) -> RegistryDefinition:
    """Insert a new definition in the caller's transaction; its initial state is DRAFT.

    No result or lifecycle transition is inserted. Duplicate versions are refused by
    the existing registry API. The caller owns commit/rollback.
    """
    return register_definition(connection, definition.to_registry())
