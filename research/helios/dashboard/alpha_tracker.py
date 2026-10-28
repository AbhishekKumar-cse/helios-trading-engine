"""Evidence-derived local alpha/dataset inventory. Never a promotion registry."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TrackerRow:
    record_id: str
    alpha: str
    dataset: str
    dataset_sha256: str
    stock: str
    scope: str
    split: str
    units: str
    period: str
    performance: str
    study_screen: str
    eligible: bool
    normal_return_pct: float | None
    doubled_return_pct: float | None
    sharpe: float | None
    fitness: float | None
    trades: int | None
    blockers: str
    next_step: str
    evidence: str
    evidence_sha256: str
    market: str = "NSE"
    frequency: str = "1d"
    source_kind: str = "Audited daily study"
    version: str = ""
    run_id: str = ""
    expression: str = ""
    evidence_status: str = "Hash verified"
    trade_count_kind: str = "Study-defined trades"


VERSIONS = {
    "official_panel_drift_v1",
    "official_shock_reversal_v1",
    "official_downside_rejection_v1",
    "official_cost_hurdle_v1",
    "official_robust_drift_v1",
    "official_peer_drift_v1",
}


def _read(path: Path) -> dict[str, Any]:
    value: dict[str, Any] = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("evidence object required")
    return value


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _checked(path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    if digest(path) != manifest.get(path.name):
        raise ValueError("evidence hash mismatch")
    return _read(path)


def performance_label(normal: float | None, stressed: float | None) -> str:
    if normal is None or stressed is None:
        return "Not measured"
    if normal > 0 and stressed > 0:
        return "Positive at both costs · exploratory"
    if normal > 0:
        return "Positive base · cost fragile"
    if normal == stressed == 0:
        return "Cash only · no edge established"
    return "Non-positive after costs"


def _official_rows(directory: Path, root: Path) -> list[TrackerRow]:
    manifest = _read(directory / "artifact_hashes.json")
    protocol = _checked(directory / "protocol.json", manifest)
    result = _checked(directory / "result.json", manifest)
    audit = _checked(directory / "independent_verification.json", manifest)
    if (
        not audit["passed"]
        or audit["protocol_sha256"] != digest(directory / "protocol.json")
        or audit["result_sha256"] != digest(directory / "result.json")
        or result["eligible_alpha_count"] != 0
        or audit["panel_sha256"] != digest(directory / "panel.parquet")
    ):
        raise ValueError("unsupported or inconsistent research evidence")
    rows = []
    for path in sorted(directory.glob("*_summary.json")):
        summary = _checked(path, manifest)
        split, window = summary["split"], int(summary["window"])
        for unit, label in (("whole", "Whole shares"), ("fractional", "Fractional diagnostic")):
            base = summary["accounts"][f"{unit}_cost1"]
            stressed = summary["accounts"][f"{unit}_cost2"]
            normal_account = _checked(
                directory / f"{split}_{window}_{unit}_cost1_candidate.json", manifest
            )
            stress_account = _checked(
                directory / f"{split}_{window}_{unit}_cost2_candidate.json", manifest
            )
            if (
                normal_account["summary"] != base["candidate"]
                or stress_account["summary"] != stressed["candidate"]
            ):
                raise ValueError("account summary mismatch")
            complete = base["candidate_status"] == stressed["candidate_status"] == "COMPLETE"
            normal = float(base["candidate"]["net_return"]) if complete else None
            stress = float(stressed["candidate"]["net_return"]) if complete else None
            stocks = sorted({t["symbol"] for t in normal_account["trades"]})
            bounds = protocol[split.lower()]
            rows.append(
                TrackerRow(
                    record_id=f"{directory.name}:{split}:{window}:{unit}",
                    alpha=protocol.get("hypothesis_id", f"body_drift_{window}"),
                    dataset="Official NSE daily · retrospective basket",
                    dataset_sha256=audit["panel_sha256"],
                    stock=", ".join(stocks) or "No funded stock",
                    scope="Basket selection",
                    split=split,
                    units=label,
                    period=f"{bounds[0]} to {bounds[1]}",
                    performance=performance_label(normal, stress)
                    if complete
                    else "Invalid account",
                    study_screen="Passed" if summary["admitted"] else "Failed original screen",
                    eligible=False,
                    normal_return_pct=None if normal is None else normal * 100,
                    doubled_return_pct=None if stress is None else stress * 100,
                    sharpe=base["candidate"]["sharpe"] if complete else None,
                    fitness=summary["gates"][unit].get("fitness") if complete else None,
                    trades=base["candidate"]["trade_pairs"] if complete else None,
                    blockers="Uncertified source/execution; daily cadence; exposed history",
                    next_step="New stock-specific protocol and fresh confirmation required",
                    evidence=str(path.relative_to(root)),
                    evidence_sha256=digest(path),
                )
            )
    return rows


def _stock_rows(directory: Path, root: Path) -> list[TrackerRow]:
    manifest = _read(directory / "artifact_hashes.json")
    protocol = _checked(directory / "protocol.json", manifest)
    candidate = _checked(directory / "candidate.json", manifest)
    if (
        candidate["protocol_sha256"] != digest(directory / "protocol.json")
        or not candidate["historical_parity_passed"]
        or candidate["eligible"]
        or candidate["forward_evaluations"] != 0
        or candidate["forward_sessions_observed"] != 0
        or candidate["collector_running"]
        or candidate["future_status"] != "NOT_STARTED"
        or candidate["dataset_sha256"] != digest(directory / "bse_exposed_2022_2023.parquet")
    ):
        raise ValueError("inconsistent stock candidate evidence")
    for stress in (1, 2):
        ledger = _checked(directory / f"historical_cost{stress}.json", manifest)
        if ledger["summary"] != candidate["historical"][f"cost{stress}"]:
            raise ValueError("stock parity summary mismatch")
    a, b = candidate["historical"]["cost1"], candidate["historical"]["cost2"]
    evidence = str((directory / "candidate.json").relative_to(root))
    shared = dict(
        alpha=candidate["alpha_id"],
        stock="BSE",
        units="Whole shares",
        eligible=False,
        blockers="Fresh confirmation pending; source/execution and cadence uncertified",
        evidence=evidence,
        evidence_sha256=digest(directory / "candidate.json"),
    )
    return [
        TrackerRow(
            record_id=f"{directory.name}:parity",
            dataset=candidate["dataset_id"],
            dataset_sha256=candidate["dataset_sha256"],
            scope="Single stock · historical parity",
            split="Exposed TRAIN",
            period="2023-01-01 to 2023-12-31",
            performance=performance_label(a["net_return"], b["net_return"]),
            study_screen="Implementation parity passed · not fresh validation",
            normal_return_pct=a["net_return"] * 100,
            doubled_return_pct=b["net_return"] * 100,
            sharpe=a["sharpe"],
            fitness=None,
            trades=a["trades"],
            next_step="Preserved BSE lead; selected after seeing historical results",
            **shared,
        ),
        TrackerRow(
            record_id=f"{directory.name}:forward",
            dataset="BSE official daily · future receipts",
            dataset_sha256="",
            scope="Single stock · forward plan",
            split="Forward · not started",
            period=(
                f"From {protocol['forward_plan']['not_before']} · "
                "60 warm-up + 60 measurement sessions"
            ),
            performance="Forward not started",
            study_screen="Not evaluated",
            normal_return_pct=None,
            doubled_return_pct=None,
            sharpe=None,
            fitness=None,
            trades=None,
            next_step="Collector not running; verified calendars and 120 future sessions required",
            **shared,
        ),
    ]


SINGLE_STOCK_SPECS = {
    "single_stock_compression_v1": ("reliance_compression60_v1", "RELIANCE", "INE002A01018"),
    "single_stock_pressure_v1": ("icici_pressure60_v1", "ICICIBANK", "INE090A01021"),
}


def _single_stock_rows(directory: Path, root: Path) -> list[TrackerRow]:
    manifest = _read(directory / "artifact_hashes.json")
    protocol = _checked(directory / "protocol.json", manifest)
    result = _checked(directory / "result.json", manifest)
    audit = _checked(directory / "independent_verification.json", manifest)
    if (
        (protocol["alpha_id"], protocol["symbol"], protocol["isin"])
        != SINGLE_STOCK_SPECS[protocol["version"]]
        or result["eligible"]
        or not audit["passed"]
        or audit["accounts_replayed"] != 12
        or audit["protocol_sha256"] != digest(directory / "protocol.json")
        or result["protocol_sha256"] != audit["protocol_sha256"]
        or audit["result_sha256"] != digest(directory / "result.json")
        or result["dataset_sha256"] != digest(directory / "records.parquet")
        or audit["dataset_sha256"] != result["dataset_sha256"]
        or any(
            result[k] != 0
            for k in (
                "actual_orders",
                "actual_fills",
                "registry_writes",
                "valid_evaluations",
                "test_accesses",
            )
        )
    ):
        raise ValueError("inconsistent single-stock study evidence")
    for name, summary in result["accounts"].items():
        if (
            name
            not in {
                f"{u}_cost{c}_{a}"
                for u in ("whole", "fractional")
                for c in (1, 2)
                for a in ("candidate", "always", "frequency")
            }
            or _checked(directory / f"{name}.json", manifest)["summary"] != summary
        ):
            raise ValueError("account summary mismatch")
    if len(result["accounts"]) != 12:
        raise ValueError("complete diagnostic accounts required")
    rows = []
    for unit, label in (("whole", "Whole shares"), ("fractional", "Fractional diagnostic")):
        base = result["accounts"][f"{unit}_cost1_candidate"]
        stress = result["accounts"][f"{unit}_cost2_candidate"]
        normal, doubled = float(base["net_return"]), float(stress["net_return"])
        rows.append(
            TrackerRow(
                record_id=f"{directory.name}:TRAIN:{unit}",
                alpha=protocol["alpha_id"],
                dataset=f"{protocol['symbol']} official daily · exposed 2023",
                dataset_sha256=result["dataset_sha256"],
                stock=protocol["symbol"],
                scope="Single stock · exploratory research",
                split="Exposed TRAIN",
                units=label,
                period=" to ".join(protocol["train"]),
                performance=performance_label(normal, doubled),
                study_screen="Passed exploratory screen"
                if result["screen_passed"]
                else "Failed original screen",
                eligible=False,
                normal_return_pct=normal * 100,
                doubled_return_pct=doubled * 100,
                sharpe=base["sharpe"],
                fitness=None,
                trades=base["trades"],
                blockers="; ".join(result["blockers"]),
                next_step="Fresh confirmation and certification required"
                if result["screen_passed"]
                else "Retain failed hypothesis; preregister the next experiment separately",
                evidence=str((directory / "result.json").relative_to(root)),
                evidence_sha256=digest(directory / "result.json"),
            )
        )
    return rows


def collect_rows(root: Path) -> tuple[list[TrackerRow], list[str]]:
    """Import supported snapshots only, preserving invalid/incomplete-source notices."""
    rows: list[TrackerRow] = []
    issues = []
    for directory in sorted((root / "reports_out/equity_research").glob("*")):
        if not (directory / "protocol.json").is_file():
            continue
        try:
            version = _read(directory / "protocol.json").get("version")
            if version in VERSIONS:
                if not (directory / "result.json").exists():
                    issues.append(f"{directory.name}: incomplete attempt, no result invented")
                    continue
                rows.extend(_official_rows(directory, root))
            elif version == "bse_single_stock_v1":
                if not (directory / "candidate.json").exists():
                    issues.append(
                        f"{directory.name}: incomplete stock preparation, no result invented"
                    )
                    continue
                rows.extend(_stock_rows(directory, root))
            elif version in SINGLE_STOCK_SPECS:
                if not (directory / "artifact_hashes.json").exists():
                    issues.append(f"{directory.name}: incomplete study, no result invented")
                    continue
                rows.extend(_single_stock_rows(directory, root))
        except (OSError, ValueError, KeyError, TypeError):
            issues.append(
                f"{directory.name}: evidence unavailable or failed integrity verification"
            )
    rows.sort(
        key=lambda r: (
            r.alpha != "bse_body60_v1",
            r.scope == "Single stock · forward plan",
            r.alpha,
            r.record_id,
        )
    )
    if len({r.record_id for r in rows}) != len(rows):
        raise ValueError("duplicate tracker identity")
    return rows, issues


def write_csv(path: Path, rows: list[TrackerRow]) -> None:
    """Atomic derived snapshot; no source evidence or registry mutation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=path.name + ".",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            writer = csv.DictWriter(stream, fieldnames=[f.name for f in fields(TrackerRow)])
            writer.writeheader()
            writer.writerows(asdict(r) for r in rows)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def refresh_tracker(
    root: Path, *, include_registry: bool = False
) -> tuple[list[TrackerRow], list[str]]:
    rows, issues = collect_rows(root)
    if include_registry:
        from helios.dashboard.registry_tracker import collect_registered

        try:
            registered, notices = collect_registered(root)
            rows.extend(registered)
            issues.extend(notices)
        except Exception:
            # Connection errors may include credentials: never render their text.
            issues.append(
                "Registry unavailable; showing retained audited daily studies only. "
                "Retry refresh after database recovery."
            )
    write_csv(root / "local_state/alpha_tracker.csv", rows)
    return rows, issues
