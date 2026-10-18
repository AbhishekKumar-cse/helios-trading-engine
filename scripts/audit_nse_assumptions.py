"""Read-only NSE source, corporate-event, known membership, calendar and charge audit."""

import argparse
import json
import shutil
from collections import Counter
from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

from helios.common.db import get_engine
from helios.common.lineage import PROJECT_ROOT, git_commit, git_is_dirty
from helios.data.equities import constituents, sha256, write_json
from helios.equities.calendar import normal_sessions
from helios.equities.charges import ChargeTrade, estimate_intraday_charges
from helios.equities.pipeline import registry_fingerprint
from helios.equities.validation import (
    bhavcopy,
    corporate_events,
    known_preinclusion_rows,
    price_scale_check,
    verified_references,
)


def bound_file(root: Path, relative: str, digest: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or sha256(path) != digest:
        raise ValueError("audit input path or fingerprint mismatch")
    return path


def audit(snapshot: Path, references: Path, supplement: Path, output: Path) -> None:
    if output.with_suffix(".json").exists() or output.with_suffix(".md").exists():
        raise ValueError("audit output already exists; preserve it and choose a new version")
    manifest_path = snapshot / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    snapshot_digest = sha256(manifest_path)
    refs = verified_references(references)
    reference_protocol = json.loads((references / "protocol.json").read_text())
    if reference_protocol["snapshot_manifest_sha256"] != snapshot_digest:
        raise ValueError("reference collection belongs to another source snapshot")
    if sha256(references / "collector_source.py") != reference_protocol["source_sha256"]:
        raise ValueError("archived collection source mismatch")
    supp = json.loads((supplement / "manifest.json").read_text())
    for record in supp["sources"]:
        bound_file(supplement, record["path"], record["sha256"])
    facts_path = PROJECT_ROOT / "configs/equities/validation_reference_v1.json"
    facts = json.loads(facts_path.read_text())
    runtime = PROJECT_ROOT / "reports_out/nse_validation" / (output.stem + "_source")
    runtime.mkdir(parents=True, exist_ok=False)
    runtime_hashes = {}
    for name in (
        "scripts/audit_nse_assumptions.py",
        "research/helios/equities/charges.py",
        "research/helios/equities/validation.py",
        "configs/equities/validation_reference_v1.json",
    ):
        original = PROJECT_ROOT / name
        archived = runtime / name
        archived.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, archived)
        runtime_hashes[name] = sha256(original)
        assert sha256(archived) == runtime_hashes[name]
    write_json(runtime / "manifest.json", dict(base_commit=git_commit(), files=runtime_hashes))
    start, end = date.fromisoformat(facts["start"]), date.fromisoformat(facts["end"])
    if start != date(2025, 1, 1) or end != date(2026, 6, 30):
        raise ValueError("audit cannot load price TEST dates")
    roster_path = bound_file(snapshot, "constituents.csv", manifest["universe_sha256"])
    roster = constituents(roster_path.read_bytes())
    bound_file(snapshot, "protocol.json", manifest["protocol_sha256"])
    journal = bound_file(snapshot, "requests.jsonl", manifest["requests_sha256"])
    registry_before = registry_fingerprint(get_engine())
    captured_review = json.loads(
        (PROJECT_ROOT / "docs/research/nse_equity_closeout_20261018.json").read_text()
    )
    assert registry_before == captured_review["crypto_registry_unchanged"]
    raw_count, raw_budget = 0, Counter()
    for line in journal.read_text().splitlines():
        request = json.loads(line)
        path = bound_file(snapshot, request["path"], request["sha256"])
        raw_count += 1
        if request["start"] in ("2025-02-01", "2026-02-01"):
            candles = json.loads(path.read_bytes())["data"]["candles"]
            for day in facts["special_full_sessions"]:
                raw_budget[day] += sum(str(row[0]).startswith(day + "T") for row in candles)
    official = {}
    for key, record in refs.items():
        if key.startswith("bhav_") and record["status"] == 200:
            day = date.fromisoformat(key.removeprefix("bhav_"))
            official[day.isoformat()] = bhavcopy((references / record["path"]).read_bytes(), day)
    holidays2025 = set(facts["normal_weekday_holidays_2025"])
    normal2025 = {
        day.date().isoformat() for day in pd.date_range("2025-01-01", "2025-12-31", freq="B")
    }
    normal2025 -= holidays2025
    calendar_descriptor = json.loads((snapshot / "calendar.json").read_text())
    calendar_path = bound_file(snapshot, calendar_descriptor["path"], calendar_descriptor["sha256"])
    normal2026 = set(normal_sessions(calendar_path, date(2026, 1, 1), end))
    normal = normal2025 | normal2026
    all_full = normal | set(facts["special_full_sessions"])
    company_rows, events, comparisons = [], [], []
    retained_budget: Counter[str] = Counter()
    known_rules = {row["symbol"]: row for row in facts["known_inclusions"]}
    for member in roster:
        symbol, isin = member["Symbol"], member["ISIN Code"]
        source_record = next(row for row in manifest["files"] if row["symbol"] == symbol)
        path = bound_file(snapshot, source_record["path"], source_record["sha256"])
        frame = pd.read_parquet(path)
        if frame.empty or set(frame.symbol) != {symbol} or frame.open_time.duplicated().any():
            raise ValueError("snapshot identity/uniqueness mismatch")
        if not frame.session_date.between(start.isoformat(), end.isoformat()).all():
            raise ValueError("snapshot contains a price outside the declared TRAIN/VALID range")
        if not np.isfinite(frame[["open", "high", "low", "close", "volume"]].to_numpy()).all():
            raise ValueError("nonfinite minute source")
        counts = frame.groupby("session_date").size()
        for day in facts["special_full_sessions"]:
            retained_budget[day] += int(counts.get(day, 0))
        action_ref = refs["actions_" + symbol]
        returned_events = (
            corporate_events((references / action_ref["path"]).read_bytes(), symbol, start, end)
            if action_ref["status"] == 200
            else []
        )
        for event in returned_events:
            event["snapshot_isin_matches_reported"] = event["reported_isin"] == isin
        events.extend(returned_events)
        rule = known_rules.get(symbol)
        excluded = 0
        if rule is not None:
            if refs[rule["reference"]]["status"] != 200:
                raise ValueError("membership rule has no retained successful primary reference")
            if "document_symbol" in rule:
                if not any(
                    ((daily.ISIN == isin) & (daily.TckrSymb == rule["document_symbol"])).any()
                    for daily in official.values()
                ):
                    raise ValueError(
                        "historical symbol alias lacks observed exchange ISIN evidence"
                    )
            excluded = int(
                known_preinclusion_rows(
                    frame.session_date, included_on=date.fromisoformat(rule["effective"])
                ).sum()
            )
        aliases = set()
        for day, daily in official.items():
            matched = daily.loc[daily.ISIN == isin]
            identity = "ISIN"
            if matched.empty:
                matched = daily.loc[daily.TckrSymb == symbol]
                identity = "SYMBOL_ONLY_REQUIRES_IDENTITY_REVIEW"
            if len(matched) != 1:
                comparisons.append(
                    dict(symbol=symbol, day=day, status="NO_UNAMBIGUOUS_EQ_IDENTITY")
                )
                continue
            record = matched.iloc[0]
            aliases.add(str(record.TckrSymb))
            result = price_scale_check(frame.loc[frame.session_date == day], record)
            comparisons.append(
                dict(
                    symbol=symbol,
                    day=day,
                    snapshot_isin=isin,
                    official_isin=record.ISIN,
                    official_symbol=record.TckrSymb,
                    identity=identity,
                    **result,
                )
            )
        company_rows.append(
            dict(
                symbol=symbol,
                isin=isin,
                rows=len(frame),
                sha256=source_record["sha256"],
                zero_volume_minutes=int((frame.volume == 0).sum()),
                missing_full_sessions=sorted(all_full - set(counts.index)),
                incomplete_full_sessions={
                    d: int(n) for d, n in counts.items() if d in all_full and n != 375
                },
                unexpected_dates=sorted(
                    set(counts.index) - all_full - set(facts["special_short_sessions"])
                ),
                retained_short_sessions={
                    d: int(counts.get(d, 0)) for d in facts["special_short_sessions"]
                },
                known_preinclusion_minutes=excluded,
                known_inclusion_rule=rule,
                observed_exchange_symbols=sorted(aliases),
                actions_http_status=action_ref["status"],
                returned_actions=len(returned_events),
            )
        )
        print(symbol, "audited", "known pre-inclusion rows", excluded, flush=True)
    costs = []
    root = PROJECT_ROOT / "reports_out/equity_research/nse_minute_round1"
    if (
        sha256(root / "summary.json")
        != captured_review["rounds"]["nse_minute_round1"]["summary_sha256"]
    ):
        raise ValueError("minute summary differs from the committed closeout review")
    summary = json.loads((root / "summary.json").read_text())
    for row in summary["results"]:
        if row["status"] == "INVALID":
            continue
        path = Path(row["artifact"])
        if sha256(path) != row["artifact_sha256"]:
            raise ValueError("retained execution result changed")
        artifact = json.loads(path.read_text())
        if len({fill["fill_id"] for fill in artifact["fills"]}) != len(artifact["fills"]):
            raise ValueError("duplicate execution fill")
        trades = [
            ChargeTrade(
                pd.Timestamp(fill["timestamp"], unit="us", tz="UTC")
                .tz_convert("Asia/Kolkata")
                .date(),
                fill["symbol"],
                fill["order_id"],
                fill["side"],
                Decimal(fill["quantity"]),
                Decimal(fill["price"]),
            )
            for fill in artifact["fills"]
        ]
        estimate = estimate_intraday_charges(trades)
        costs.append(
            dict(
                candidate=row["candidate"],
                run_id=row["run_id"],
                artifact_sha256=row["artifact_sha256"],
                actual_base_proxy_fees_inr=artifact["fees_total_inr"],
                reference_charge_estimate={**asdict(estimate), "total": estimate.total},
                original_fills_unchanged=True,
                not_a_resimulation=True,
            )
        )
    registry_after = registry_fingerprint(get_engine())
    assert registry_before == registry_after
    assert sha256(manifest_path) == snapshot_digest
    assert all(sha256(PROJECT_ROOT / name) == digest for name, digest in runtime_hashes.items())
    result = dict(
        version="nse_assumption_audit_v1",
        audited_at=datetime.now(UTC).isoformat(),
        decision="BLOCKED_PENDING_SOURCE_AND_PROTOCOL_REPAIR",
        g7_relaxed=False,
        code_commit=git_commit(),
        code_dirty=git_is_dirty(),
        runtime_archive=str(runtime.relative_to(PROJECT_ROOT)),
        runtime_manifest_sha256=sha256(runtime / "manifest.json"),
        audit_source_sha256=sha256(Path(__file__)),
        facts_sha256=sha256(facts_path),
        snapshot_manifest_sha256=snapshot_digest,
        references_manifest_sha256=sha256(references / "manifest.json"),
        supplement_manifest_sha256=sha256(supplement / "manifest.json"),
        raw_months_verified=raw_count,
        companies=len(company_rows),
        total_minute_rows=sum(r["rows"] for r in company_rows),
        reference_statuses=dict(Counter(str(r["status"]) for r in refs.values())),
        action_events=len(events),
        action_kinds=dict(Counter(r["kind"] for r in events)),
        known_preinclusion_minutes=sum(r["known_preinclusion_minutes"] for r in company_rows),
        known_missing_historical_members=facts["known_missing_historical_members"],
        calendar=dict(
            normal_sessions=len(normal),
            full_sessions_including_reviewed_specials=len(all_full),
            raw_budget_session_candles=dict(raw_budget),
            retained_budget_session_minutes=dict(retained_budget),
            short_sessions=facts["special_short_sessions"],
        ),
        price_comparison_counts=dict(Counter(r["status"] for r in comparisons)),
        source_reference_records=refs,
        supplemental_reference_records=supp["sources"],
        company_rows=company_rows,
        corporate_events=events,
        price_comparisons=comparisons,
        charge_diagnostics=costs,
        registry_before=registry_before,
        registry_after=registry_after,
        source_snapshot_modified=False,
        research_results_modified=False,
        test_accesses=registry_after["test_accesses"],
        limitations=[
            "Known membership violations are a lower bound, not a complete PIT universe.",
            "Retrospective ex-dates do not establish announcement availability.",
            "Daily/minute scope differs. Scale flags need review, never automatic rescaling.",
            "Current public brokerage is a scenario, not a proven dated account tariff.",
            "Charge diagnostics reuse retained fills; no new strategy P&L, model fit or ranking.",
            "GST/stamp/brokerage rounding and contract-note reconciliation remain unverified.",
            "Spreads, impact, live-feed acceptance and causal outage policy remain unverified.",
        ],
    )
    write_json(output.with_suffix(".json"), result)
    print("Audit retained:", output.with_suffix(".json"), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("references", type=Path)
    parser.add_argument("supplement", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    audit(args.snapshot, args.references, args.supplement, args.output)
