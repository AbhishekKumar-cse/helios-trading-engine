"""Complete, hash-verified hourly round inventory, including failed attempts (138)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Connection, text

from helios.registry.api import count_versions, get_alpha
from helios.registry.results import AlphaResult, Split, Status, list_results
from helios.registry.test_access import count_test_accesses
from helios.sim.report import verified_evidence

BASELINES = ("baseline_b0", "baseline_b1", "baseline_b2")
CANDIDATES = tuple(f"hourly_h{i:02d}" for i in range(1, 9))


def comparison(results: Sequence[AlphaResult]) -> dict[str, Any]:
    if len({r.run_id for r in results}) != len(results):
        raise ValueError("search inventory must not count a retained run twice")
    comparable = [
        r
        for r in results
        if r.split is Split.VALID
        and r.status is not Status.INVALID
        and not r.dirty
        and r.fitness is not None
        and r.sharpe is not None
    ]
    best = sorted(
        comparable, key=lambda r: (-float(r.fitness or 0), r.alpha_id, r.version, r.run_id)
    )
    return dict(
        n_attempts=len(results),
        n_invalid=sum(r.status is Status.INVALID for r in results),
        n_valid_attempts=sum(r.split is Split.VALID for r in results),
        best_run_id=best[0].run_id if best else None,
        best_fitness=str(best[0].fitness) if best else None,
        explanation="No performance ranking exists when all attempts are INVALID."
        if not best
        else "Ranked clean VALID measurements by Fitness; not a promotion.",
    )


def search_inventory(connection: Connection) -> dict[str, Any]:
    entries, attempts = [], []
    for group, identifiers in (("baseline", BASELINES), ("candidate", CANDIDATES)):
        for alpha_id in identifiers:
            n_versions = count_versions(connection, alpha_id)
            if n_versions < 1:
                raise ValueError("search summary requires every baseline and candidate definition")
            results = list_results(connection, alpha_id=alpha_id, limit=10000)
            count: int = connection.execute(
                text("SELECT count(*) FROM alpha_results WHERE alpha_id=:id"), {"id": alpha_id}
            ).scalar_one()
            if count != len(results) or not results:
                raise ValueError("search summary cannot truncate or omit an attempted candidate")
            versions = {r.version for r in results}
            for version in versions:
                get_alpha(connection, alpha_id, version)
            rows = []
            for result in sorted(results, key=lambda r: (r.version, r.split.value, r.run_id)):
                evidence = verified_evidence(result)
                # Hash checks alone are insufficient if metadata names another run's evidence.
                bound = evidence["protocol"]["definition"]
                if bound["alpha_id"] != result.alpha_id or bound["version"] != result.version:
                    raise ValueError("search artifact alpha/version mismatch")
                rows.append(
                    dict(
                        run_id=result.run_id,
                        experiment_id=result.experiment_id,
                        version=result.version,
                        split=result.split.value,
                        status=result.status.value,
                        sharpe=None if result.sharpe is None else str(result.sharpe),
                        fitness=None if result.fitness is None else str(result.fitness),
                        validity=result.evaluation_json["validity"]
                        if result.evaluation_json
                        else None,
                        artifact_sha256=result.evaluation_json["artifact_sha256"]
                        if result.evaluation_json
                        else None,
                        code_commit=result.code_commit,
                        dirty=result.dirty,
                        snapshot_id=result.snapshot_id,
                        gate_results=result.gate_results,
                    )
                )
            accesses = {
                str(v): count_test_accesses(connection, alpha_id, v)
                for v in range(1, n_versions + 1)
            }
            entries.append(
                dict(
                    group=group,
                    alpha_id=alpha_id,
                    n_versions=n_versions,
                    n_attempts=len(results),
                    test_accesses=accesses,
                    attempts=rows,
                )
            )
            attempts.extend(results)
    return dict(
        scope="Three hourly baselines and eight fixed round-one candidates; all retained attempts",
        n_definitions=sum(e["n_versions"] for e in entries),
        entries=entries,
        baseline=comparison([r for r in attempts if r.alpha_id in BASELINES]),
        candidate=comparison([r for r in attempts if r.alpha_id in CANDIDATES]),
        overall=comparison(attempts),
        limitations=[
            "Simulation invalidity is not evidence of negative profitability.",
            "Model prediction accuracy/calibration are not alpha gate metrics.",
            "No gap filling, parameter reruns, TEST reading or result mutation.",
        ],
    )


def inventory_markdown(inventory: dict[str, Any]) -> str:
    lines = [
        "# Hourly round-one search effort (138)",
        "",
        "Every retained simulation attempt is counted, including preliminary batch checks.",
        "No valid candidate/baseline performance comparison is available in this round.",
        "",
        "| Group | Alpha | Versions | TRAIN attempts | VALID attempts | INVALID | TEST accesses |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for entry in inventory["entries"]:
        rows = entry["attempts"]
        lines.append(
            f"| {entry['group']} | {entry['alpha_id']} | {entry['n_versions']} | "
            f"{sum(r['split'] == 'train' for r in rows)} | "
            f"{sum(r['split'] == 'valid' for r in rows)} | "
            f"{sum(r['status'] == 'INVALID' for r in rows)} | "
            f"{sum(entry['test_accesses'].values())} |"
        )
    for group in ("baseline", "candidate", "overall"):
        row = inventory[group]
        lines.extend(
            [
                "",
                f"{group.capitalize()}: {row['n_attempts']} attempts; "
                f"{row['n_invalid']} INVALID; best VALID Fitness: "
                f"{row['best_fitness'] or 'N/A'}. {row['explanation']}",
            ]
        )
    lines.extend(
        [
            "",
            "Fixed definitions contain one preregistered parameter setting each; "
            "TRAIN/VALID and batch-check runs are attempts, not additional parameter variants.",
            "No failed or undefined metric is replaced by zero.",
            "",
        ]
    )
    return "\n".join(lines)
