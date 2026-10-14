"""Append-only selection decisions, separate from immutable measurements (140).

INVALID performance evidence remains INVALID even when a deployment decision is
REJECTED. The existing audit journal stores the decision, not rewritten results.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, text

from helios.alpha.final_test import eligibility
from helios.common.config import canonical_json, config_hash
from helios.common.lineage import git_commit
from helios.common.project_config import load_gates
from helios.registry.api import RegistryError, get_alpha
from helios.registry.experiments import get_experiment
from helios.registry.results import AlphaResult, Split, Status, get_result
from helios.registry.test_access import MAX_TEST_ACCESSES, count_test_accesses
from helios.sim.report import verified_evidence


class SelectionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    round_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    alpha_id: str
    version: int = Field(ge=1)
    status: Literal["PROMOTED", "REJECTED"]
    valid_run_id: str
    test_run_id: str | None
    reasons: tuple[str, ...] = Field(min_length=1)
    evidence_hashes: dict[str, str]
    gate_config_hash: str
    actor: str = Field(min_length=2)
    code_commit: str = Field(pattern=r"^[0-9a-f]{40}$")


def selection_outcome(
    valid: AlphaResult, test: AlphaResult | None
) -> tuple[Literal["PROMOTED", "REJECTED"], tuple[str, ...]]:
    if valid.status is Status.INVALID:
        return "REJECTED", ("INVALID_VALID_MEASUREMENT", "NO_PERFORMANCE_CONCLUSION")
    reasons = eligibility(valid)
    if reasons:
        return "REJECTED", reasons
    if test is None:
        return "REJECTED", ("NO_FINAL_TEST_CONFIRMATION",)
    if (test.alpha_id, test.version, test.snapshot_id) != (
        valid.alpha_id,
        valid.version,
        valid.snapshot_id,
    ):
        raise RegistryError("TEST confirmation must match the frozen VALID alpha/version/snapshot")
    reasons = eligibility(test, Split.TEST)
    if reasons:
        return "REJECTED", tuple("TEST_" + reason for reason in reasons)
    return "PROMOTED", ("ALL_ACCEPTED_VALID_AND_TEST_GATES_PASS",)


def get_selection(
    connection: Connection, alpha_id: str, version: int, round_id: str
) -> SelectionDecision | None:
    row = connection.execute(
        text(
            "SELECT payload,after_hash FROM audit_events WHERE action='ALPHA_SELECTION_DECISION' "
            "AND subject=:subject AND payload->>'round_id'=:round ORDER BY audit_id DESC LIMIT 1"
        ),
        {"subject": f"{alpha_id}:v{version}", "round": round_id},
    ).one_or_none()
    if row is None:
        return None
    decision = SelectionDecision.model_validate(row.payload)
    if hashlib.sha256(canonical_json(decision).encode()).hexdigest() != row.after_hash:
        raise RegistryError("selection decision hash mismatch")
    return decision


def record_selection(
    connection: Connection,
    *,
    round_id: str,
    valid_run_id: str,
    test_run_id: str | None = None,
    actor: str,
) -> SelectionDecision:
    valid = get_result(connection, valid_run_id)
    if valid.split is not Split.VALID:
        raise RegistryError("selection requires a frozen VALID result")
    get_alpha(connection, valid.alpha_id, valid.version)
    test = None if test_run_id is None else get_result(connection, test_run_id)
    if test is not None:
        experiment = get_experiment(connection, test.experiment_id)
        frozen = experiment.params.get("selection", {})
        if (
            frozen.get("valid_run_id") != valid.run_id
            or frozen.get("alpha_id") != valid.alpha_id
            or frozen.get("version") != valid.version
            or experiment.snapshot_id != valid.snapshot_id
            or valid.created_at is None
            or experiment.pre_registered_at is None
            or experiment.pre_registered_at <= valid.created_at
        ):
            raise RegistryError("TEST experiment must freeze this earlier VALID evidence")
        metadata = test.evaluation_json or {}
        access = connection.execute(
            text("SELECT alpha_id,version,snapshot_id FROM test_set_access WHERE access_id=:id"),
            {"id": metadata.get("test_access_id")},
        ).one_or_none()
        if access is None or tuple(access) != (test.alpha_id, test.version, test.snapshot_id):
            raise RegistryError("TEST confirmation lacks its matching reserved access")
        if count_test_accesses(connection, test.alpha_id, test.version) > MAX_TEST_ACCESSES:
            raise RegistryError("TEST access budget exceeded")
    hashes = {}
    for result in (valid,) if test is None else (valid, test):
        evidence = verified_evidence(result)
        definition = evidence["protocol"]["definition"]
        if (definition["alpha_id"], definition["version"]) != (result.alpha_id, result.version):
            raise RegistryError("selection artifact identity mismatch")
        assert result.evaluation_json is not None
        hashes[result.run_id] = str(result.evaluation_json["artifact_sha256"])
    status, reasons = selection_outcome(valid, test)
    decision = SelectionDecision(
        round_id=round_id,
        alpha_id=valid.alpha_id,
        version=valid.version,
        status=status,
        valid_run_id=valid.run_id,
        test_run_id=test_run_id,
        reasons=reasons,
        evidence_hashes=hashes,
        actor=actor,
        gate_config_hash=config_hash(load_gates()),
        code_commit=git_commit(),
    )
    subject = f"{valid.alpha_id}:v{valid.version}"
    connection.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:scope))"),
        {"scope": "selection:" + round_id + ":" + subject},
    )
    previous = get_selection(connection, valid.alpha_id, valid.version, round_id)
    if previous is not None:
        if previous.model_dump(exclude={"code_commit", "actor"}) != decision.model_dump(
            exclude={"code_commit", "actor"}
        ):
            raise RegistryError(
                "round decision already exists with different evidence; use a new round"
            )
        return previous
    payload = canonical_json(decision)
    connection.execute(
        text(
            "INSERT INTO audit_events (ts,actor,action,subject,after_hash,justification,payload) "
            "VALUES (:ts,:actor,'ALPHA_SELECTION_DECISION',:subject,:hash,:reason,"
            "CAST(:payload AS jsonb))"
        ),
        dict(
            ts=int(datetime.now(UTC).timestamp() * 1_000_000),
            actor=actor,
            subject=subject,
            hash=hashlib.sha256(payload.encode()).hexdigest(),
            reason="; ".join(reasons),
            payload=payload,
        ),
    )
    return decision
