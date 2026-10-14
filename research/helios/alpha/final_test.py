"""Freeze a shortlist from valid, clean VALID gates before reading TEST (139)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection

from helios.alpha.search_effort import CANDIDATES
from helios.common.config import config_hash
from helios.common.project_config import HorizonFamily, load_gates
from helios.registry.api import get_alpha
from helios.registry.results import AlphaResult, Split, Status, list_results
from helios.registry.test_access import MAX_TEST_ACCESSES, count_test_accesses
from helios.sim.gates import gate_decisions
from helios.sim.report import verified_evidence


def eligibility(result: AlphaResult, required_split: Split = Split.VALID) -> tuple[str, ...]:
    reasons = []
    if result.split is not required_split:
        reasons.append(f"NOT_{required_split.value.upper()}_SPLIT")
    if result.status not in (Status.EVALUATED, Status.PROMOTED):
        reasons.append(
            "INVALID_MEASUREMENT" if result.status is Status.INVALID else "VALID_GATES_FAILED"
        )
    if result.dirty:
        reasons.append("DIRTY_SOURCE")
    gates = load_gates()
    metadata = result.evaluation_json or {}
    if result.gate_config_id != gates.version or metadata.get("gate_config_hash") != config_hash(
        gates
    ):
        reasons.append("GATE_CONFIG_MISMATCH")
    if not {f"G{i}" for i in range(1, 7)}.issubset(result.gate_results) or not all(
        result.gate_results.values()
    ):
        reasons.append("INCOMPLETE_OR_FAILED_GATES")

    def number(value: Any) -> float | None:
        return None if value is None else float(value)

    recomputed = gate_decisions(
        sharpe=number(result.sharpe),
        fitness=number(result.fitness),
        turnover=number(result.turnover),
        split=result.split,
        positive_fraction=number(result.stability_positive_fraction),
        cost_stress_sharpe=number(result.cost_stress_sharpe),
        gates=gates,
    )
    if not recomputed.all_passed or result.periods < 2:
        reasons.append("METRICS_DO_NOT_PASS_GATES")
    return tuple(reasons)


@dataclass(frozen=True)
class FinalTestSelection:
    alpha_id: str
    version: int
    valid_run_id: str
    snapshot_id: str
    fitness: str


def rank_shortlist(
    results: Sequence[AlphaResult], maximum: int = 2
) -> tuple[FinalTestSelection, ...]:
    if type(maximum) is not int or not 1 <= maximum <= 3:
        raise ValueError("final TEST shortlist is limited to at most three candidates")
    eligible = [r for r in results if not eligibility(r)]
    if len({(r.alpha_id, r.version) for r in eligible}) != len(eligible):
        raise ValueError("shortlist must contain one frozen VALID attempt per alpha version")
    ranked = sorted(eligible, key=lambda r: (-float(r.fitness or 0), r.alpha_id, r.version))[
        :maximum
    ]
    return tuple(
        FinalTestSelection(r.alpha_id, r.version, r.run_id, r.snapshot_id, str(r.fitness))
        for r in ranked
    )


def prepare_final_test(connection: Connection, maximum: int = 2) -> dict[str, Any]:
    results, excluded, budgets = [], {}, {}
    for alpha_id in CANDIDATES:
        definition = get_alpha(connection, alpha_id)
        if definition.horizon_family is not HorizonFamily.HOURLY:
            raise ValueError("hourly final TEST requires the registered hourly family")
        rows = list_results(
            connection,
            alpha_id=alpha_id,
            version=definition.version,
            split=Split.VALID,
            limit=10000,
        )
        if not rows:
            excluded[alpha_id] = ["MISSING_VALID_RESULT"]
            continue
        # Use latest evidence, never hide a newer failure by selecting an older success.
        selected = max(
            rows, key=lambda r: (r.created_at.timestamp() if r.created_at else 0, r.run_id)
        )
        evidence = verified_evidence(selected)
        bound = evidence["protocol"]["definition"]
        if (bound["alpha_id"], bound["version"]) != (alpha_id, definition.version):
            raise ValueError("final TEST evidence identity mismatch")
        reasons = list(eligibility(selected))
        used = count_test_accesses(connection, alpha_id, definition.version)
        budgets[alpha_id] = used
        if used >= MAX_TEST_ACCESSES:
            reasons.append("TEST_BUDGET_EXHAUSTED")
        elif used:
            reasons.append("ALREADY_CONFIRMED_NO_AUTOMATIC_RETEST")
        if reasons:
            excluded[alpha_id] = reasons
        else:
            results.append(selected)
    shortlist = rank_shortlist(results, maximum)
    return dict(
        selected=[s.__dict__ for s in shortlist],
        excluded=excluded,
        test_accesses_before=budgets,
        maximum_candidates=maximum,
        decision="READY" if shortlist else "SKIPPED_NO_ELIGIBLE_CANDIDATES",
        policy="Latest clean VALID, accepted G1-G6, Fitness rank; freeze before TEST",
        max_accesses_per_version=MAX_TEST_ACCESSES,
    )
