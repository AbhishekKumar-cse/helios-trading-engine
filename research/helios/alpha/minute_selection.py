"""Review the frozen minute round using the existing final-TEST eligibility policy."""

import hashlib
import json
from typing import Any

from sqlalchemy import Connection, text

from helios.alpha.final_test import eligibility, rank_shortlist
from helios.common.project_config import HorizonFamily
from helios.registry.api import get_alpha
from helios.registry.results import Split, list_results
from helios.registry.selection import record_selection
from helios.registry.test_access import count_test_accesses
from helios.sim.report import verified_evidence

MINUTE_CANDIDATES = (
    *(f"minute_b{i}" for i in range(3)),
    *(f"minute_h{i:02d}" for i in range(1, 9)),
    "minute_ml_v1",
)


def review_minute(connection: Connection) -> dict[str, Any]:
    reviewed, eligible = [], []
    for alpha_id in MINUTE_CANDIDATES:
        definition = get_alpha(connection, alpha_id)
        if definition.version != 1 or definition.horizon_family is not HorizonFamily.MINUTE:
            raise ValueError("round one requires its frozen minute version-one definitions")
        rows = list_results(
            connection, alpha_id=alpha_id, version=1, split=Split.VALID, limit=10000
        )
        count: int = connection.execute(
            text(
                "SELECT count(*) FROM alpha_results "
                "WHERE alpha_id=:id AND version=1 AND split='valid'"
            ),
            dict(id=alpha_id),
        ).scalar_one()
        if not rows or count != len(rows):
            raise ValueError("all retained minute VALID attempts must be reviewed")
        result = max(
            rows, key=lambda r: (r.created_at.timestamp() if r.created_at else 0, r.run_id)
        )
        evidence = verified_evidence(result)
        protocol = evidence["protocol"]
        bound = protocol["definition"]
        if (
            (bound["alpha_id"], bound["version"], bound["horizon_family"])
            != (alpha_id, 1, HorizonFamily.MINUTE.value)
            or protocol["split"] != "valid"
            or evidence["source"]
            != dict(commit=result.code_commit, dirty=result.dirty, seed=result.seed)
            or hashlib.sha256(json.dumps(protocol, sort_keys=True).encode()).hexdigest()
            != result.config_hash
        ):
            raise ValueError("retained minute evidence identity/lineage mismatch")
        reasons = list(eligibility(result))
        used = count_test_accesses(connection, alpha_id, 1)
        if used:
            reasons.append("ALREADY_CONFIRMED_NO_AUTOMATIC_RETEST")
        if not reasons:
            eligible.append(result)
        reviewed.append(
            dict(
                alpha_id=alpha_id,
                version=1,
                valid_run_id=result.run_id,
                status=result.status.value,
                reasons=reasons,
                test_accesses=used,
                retained_valid_attempts=len(rows),
                gate_results=result.gate_results,
                experiment_id=result.experiment_id,
                code_commit=result.code_commit,
                config_hash=result.config_hash,
                snapshot_id=result.snapshot_id,
                seed=result.seed,
                artifact_sha256=(result.evaluation_json or {})["artifact_sha256"],
            )
        )
    shortlist = rank_shortlist(eligible, maximum=2)
    return dict(
        decision="READY" if shortlist else "SKIPPED_NO_ELIGIBLE_CANDIDATES",
        maximum_candidates=2,
        selected=[s.__dict__ for s in shortlist],
        reviewed=reviewed,
        policy="Latest clean VALID, accepted G1-G6, Fitness rank; freeze before TEST",
        global_test_accesses=connection.execute(
            text("SELECT count(*) FROM test_set_access")
        ).scalar_one(),
    )


def reject_ineligible_minute(
    connection: Connection, review: dict[str, Any]
) -> list[dict[str, Any]]:
    # Bind the decision to a fresh review in this same transaction; no stale caller plan.
    if review != review_minute(connection) or review["selected"]:
        raise ValueError("skip finalization requires unchanged evidence and no eligible candidate")
    return [
        record_selection(
            connection,
            round_id="minute_round1",
            valid_run_id=row["valid_run_id"],
            actor="helios_minute_selection",
        ).model_dump(mode="json")
        for row in review["reviewed"]
    ]
