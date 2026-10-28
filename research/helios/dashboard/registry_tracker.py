"""Read-only registry adapter; metrics require their original artifact checksum."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, text

from helios.common.db import get_engine
from helios.dashboard.alpha_tracker import TrackerRow, performance_label


def _local_path(value: str, root: Path) -> Path:
    """Handle evidence written by either supported host, without escaping the workspace."""
    normalized = value.replace("\\", "/")
    for marker in ("/reports_out/", "/data/"):
        if marker in normalized:
            normalized = normalized[normalized.index(marker) + 1 :]
            break
    path = (root / normalized).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("evidence outside project")
    return path


def registered_row(record: dict[str, Any], root: Path) -> TrackerRow:
    """Never infer an account return by negating a score or annualising it backwards."""
    meta = record.get("evaluation_json") or {}
    protocol = meta.get("protocol") or {}
    snapshot = record.get("snapshot_id") or ""
    synthetic = bool(record["spec_json"].get("is_synthetic")) or "synthetic" in str(
        record.get("source", "")
    )
    source_market = " ".join(
        str(value or "")
        for value in (record.get("source"), meta.get("market"), record["spec_json"].get("market"))
    )
    market = "Synthetic" if synthetic else ("NSE" if "nse" in source_market.lower() else "Crypto")
    interval = record.get("interval") or record["horizon_family"]
    symbol = (meta.get("validity") or {}).get("symbol") or (protocol.get("evaluation") or {}).get(
        "symbol"
    )
    # A snapshot may contain an entire universe while the run used one instrument.
    symbols = ", ".join(record.get("symbols") or [])
    status = record.get("status") or "DRAFT"
    verified = False
    artifact: dict[str, Any] = {}
    evidence = "Registry definition; no evaluation yet"
    expected_hash = str(meta.get("artifact_sha256") or "")
    try:
        path = _local_path(str(meta["artifact"]), root)
        evidence = str(path.relative_to(root.resolve()))
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected_hash:
            raise ValueError("checksum")
        artifact = json.loads(raw)
        if artifact["snapshot_id"] != snapshot or artifact["status"] != status:
            raise ValueError("identity")
        verified = True
    except (OSError, KeyError, ValueError, TypeError):
        artifact = {}
    symbol = symbol or (artifact.get("validity") or {}).get("symbol")
    gates = record.get("gate_results") or {}
    failed = [name for name, passed in gates.items() if not passed]
    reasons = list((meta.get("validity") or {}).get("reasons") or [])
    if status != "DRAFT" and not verified:
        reasons.append("ARTIFACT_UNAVAILABLE_OR_CHANGED: metrics withheld")
    reasons.extend(failed)
    if synthetic:
        reasons.append("SYNTHETIC_CORRECTNESS_ONLY")
    eligible = (
        verified
        and status == "PROMOTED"
        and bool(gates)
        and all(gates.values())
        and record.get("split") != "train"
        and not record.get("dirty")
        and not synthetic
    )
    # Cost points hold measured total returns, not annual_return from the registry.
    costs: dict[float, float] = {}
    if verified and status != "INVALID":
        for point in (artifact.get("costs") or {}).get("points", []):
            metrics = (point.get("metrics") or {}).get("metrics") or {}
            if metrics.get("total_return") is not None:
                costs[float(point["multiplier"])] = float(metrics["total_return"]) * 100
    normal, doubled = costs.get(1.0), costs.get(2.0)
    measurable = verified and status != "INVALID"
    dates = []
    family = protocol.get("policy") or {}
    split = record.get("split") or "Not evaluated"
    if split in ("train", "valid"):
        dates = [family.get(split + "_start"), family.get(split + "_end")]
    if not any(dates):
        split_dates = (
            (protocol.get("splits") or {})
            .get("families", {})
            .get(record["horizon_family"], {})
            .get(split, {})
        )
        dates = [split_dates.get("start"), split_dates.get("end")]
    period = " → ".join(str(d) for d in dates if d) or "See frozen evaluation protocol"
    expression = (protocol.get("definition") or {}).get("expression") or (
        record["spec_json"].get("expression") or ""
    )
    return TrackerRow(
        record_id="registry:"
        + str(record.get("run_id") or (record["alpha_id"] + ":" + str(record["version"]))),
        alpha=record["alpha_id"],
        dataset=f"{record.get('source') or market} · {interval} · {snapshot[:12] or 'unassigned'}",
        dataset_sha256=snapshot,
        stock=str(symbol or symbols or "Not assigned"),
        scope="Synthetic correctness fixture"
        if synthetic
        else (
            (
                "Single stock · registered evaluation"
                if market == "NSE"
                else "Single instrument · registered evaluation"
            )
            if symbol
            else "Registered universe · see protocol"
        ),
        split=split.upper(),
        units="Whole shares"
        if market == "NSE"
        else "Crypto units"
        if market == "Crypto"
        else "Fixture units",
        period=period,
        performance=performance_label(normal, doubled),
        study_screen=status,
        eligible=bool(eligible),
        normal_return_pct=normal,
        doubled_return_pct=doubled,
        sharpe=float(record["sharpe"]) if measurable and record.get("sharpe") is not None else None,
        fitness=float(record["fitness"])
        if measurable and record.get("fitness") is not None
        else None,
        trades=len(artifact["fills"])
        if measurable and isinstance(artifact.get("fills"), list)
        else None,
        blockers="; ".join(reasons)
        or (
            "No evaluated evidence"
            if status == "DRAFT"
            else "See retained gates; no promotion inferred"
        ),
        next_step="Repair recorded validity prerequisites before new research"
        if status == "INVALID"
        else "Review retained protocol and gates before a separately preregistered experiment",
        evidence=evidence,
        evidence_sha256=expected_hash,
        market=market,
        frequency=str(interval),
        source_kind="Registry",
        version=str(record["version"]),
        run_id=str(record.get("run_id") or ""),
        expression=str(expression),
        evidence_status="Hash verified"
        if verified
        else "Definition only"
        if status == "DRAFT"
        else "Unavailable / changed",
        trade_count_kind="Fill legs"
        if measurable and isinstance(artifact.get("fills"), list)
        else "Not recorded",
    )


def collect_registered(
    root: Path, engine: Engine | None = None
) -> tuple[list[TrackerRow], list[str]]:
    """One consistent read-only join, no pagination/truncation or registry mutation."""
    with (engine or get_engine()).connect() as connection:
        connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        records = (
            connection.execute(
                text("""
            SELECT d.alpha_id,d.version,d.spec_json,d.horizon_family,
                   r.run_id,r.split,r.snapshot_id,r.status,r.gate_results,r.dirty,
                   r.evaluation_json,r.sharpe,r.fitness,
                   s.source,s.interval,s.symbols
            FROM alpha_definitions d
            LEFT JOIN alpha_results r ON r.alpha_id=d.alpha_id AND r.version=d.version
            LEFT JOIN data_snapshots s ON s.snapshot_id=r.snapshot_id
            ORDER BY d.alpha_id,d.version,r.created_at DESC
        """)
            )
            .mappings()
            .all()
        )
    rows = [registered_row(dict(record), root) for record in records]
    missing = sum(row.evidence_status == "Unavailable / changed" for row in rows)
    issues = (
        [f"Registry: {missing} artifacts unavailable/changed; their performance is withheld."]
        if missing
        else []
    )
    return rows, issues
