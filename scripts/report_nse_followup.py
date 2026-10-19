"""Bind measured source, minute-breadth and PAPER safety evidence into a closeout."""

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from helios.data.equities import sha256, write_json


def report(root, tests, output):
    if output.with_suffix(".json").exists() or output.with_suffix(".md").exists():
        raise ValueError("closeout evidence must not be overwritten")
    summary_path = root / "summary.json"
    summary = json.loads(summary_path.read_text())
    verification = Path("docs/research/nse_minute_breadth_checks_20261018.json")
    checked = json.loads(verification.read_text())
    certificate_path = Path("docs/research/nse_execution_certification_20261018.json")
    certificate = json.loads(certificate_path.read_text())
    preflight_path = Path("docs/research/nse_paper_preflight_20261018.json")
    preflight = json.loads(preflight_path.read_text())
    assert checked["round_id"] == summary["round_id"]
    assert checked["protocol_sha256"] == sha256(root / "protocol.json")
    assert checked["ledger_reconciliation"] and checked["reference_fee_settlement_verified"]
    assert summary["registry_before"] == summary["registry_after"]
    assert checked["test_accesses"] == preflight["test_accesses"] == 0
    assert not certificate["g7_eligible"] and certificate["verdict"] == "NOT_CERTIFIED"
    assert sha256(Path(certificate["report_path"])) == certificate["report_sha256"]
    text = tests.read_text()
    matched = re.search(r"(\d+) passed, (\d+) deselected, (\d+) warnings", text)
    assert matched and not re.search(r"\d+ failed|\d+ error|\d+ skipped", text)
    logs = [
        tests,
        *[
            Path("reports_out/equity_closeout") / name
            for name in (
                "nse_followup_lint_final.log",
                "nse_safety_types_final.log",
            )
        ],
    ]
    assert "All checks passed!" in logs[1].read_text()
    assert "already formatted" in logs[1].read_text()
    assert "Success: no issues found" in logs[2].read_text()
    payload = dict(
        version="nse_followup_closeout_v1",
        source_certification="NOT_CERTIFIED",
        round_id=summary["round_id"],
        research_source_commit=summary["source_commit"],
        research_dirty=checked["dirty"],
        protocol_dirty=checked["protocol_dirty"],
        summary_dirty=checked["summary_dirty"],
        statuses=dict(Counter(r["status"] for r in summary["results"])),
        research_symbols=summary["research_symbols"],
        results=summary["results"],
        reconciled_base_sessions=checked["reconciled_base_sessions"],
        reconciled_base_fills=checked["reconciled_base_fills"],
        base_fees_inr=checked["base_fees_inr"],
        promoted=0,
        test_accesses=0,
        crypto_registry=summary["registry_after"],
        market_hours_validated=False,
        automatic_resume_implemented=False,
        software_safety="Synthetic PostgreSQL rollback and ownership-loss tests passed",
        full_tests_passed=int(matched[1]),
        deselected=int(matched[2]),
        warnings=int(matched[3]),
        evidence=[
            dict(path=str(p), sha256=sha256(p))
            for p in (
                summary_path,
                root / "protocol.json",
                verification,
                certificate_path,
                preflight_path,
                *logs,
            )
        ],
        remaining=[
            "Independent raw-minute/share/volume and causal-availability certification",
            "Observed executable liquidity/cost calibration and an eligible alpha",
            "Clean-source real market-hours PAPER feed/kill/crash-recovery acceptance",
            "Actual 24-hour and seven-day promoted PAPER trials, then same-date comparison",
        ],
    )
    write_json(output.with_suffix(".json"), payload)
    lines = [
        "# NSE minute breadth and PAPER safety follow-up",
        "",
        "Source assessment completed with **NOT CERTIFIED**; promotion remains blocked.",
        "The retained public data does not prove exact original minute share/volume units,",
        "causal availability or executable liquidity. See the per-company certification record.",
        "",
        f"Preregistered round `{summary['round_id']}` executes minute baselines on "
        + ", ".join(summary["research_symbols"])
        + ". All inputs, fees and gates remain fixed.",
        f"Source `{summary['source_commit']}`; evaluator dirty={checked['dirty']}.",
        f"Protocol dirty={checked['protocol_dirty']}; summary dirty={checked['summary_dirty']}.",
        "Git markers are preserved independently; evaluator results are never relabelled clean.",
        "Later PAPER safety edits do not alter the frozen research runtime.",
        "",
        "| Company | Candidate | Status | VALID daily Sharpe |",
        "|---|---|---|---:|",
    ]
    for row in summary["results"]:
        sharpe = "unavailable" if row["sharpe"] is None else f"{row['sharpe']:.6f}"
        lines.append(f"| {row['symbol']} | {row['candidate']} | {row['status']} | {sharpe} |")
    lines.extend(
        [
            "",
            f"Independent checks reconcile {checked['reconciled_base_fills']:,} base fills "
            f"and {checked['reconciled_base_sessions']:,} candidate/session replays, including",
            "reference tax settlements, cash, coverage, metrics, gates and registry outcomes.",
            "Results describe independent fixed-capital sessions, not a compounded account.",
            "No eligible alpha, TEST access, promotion or crypto-result change occurred.",
            "",
            "PAPER changes: equity-aware atomic dashboard kill; fresh-close startup; feed-silence",
            "halt/cancellation; exclusive PostgreSQL ownership with connection-loss detection;",
            "crash recovery that reconstructs durable fills and every accounting checkpoint,",
            "cancels dead simulated intents, retains open inventory and closes the scope halted.",
            "Recovery never resumes trading or invents an exit fill.",
            "",
            f"Verification: **{matched[1]} tests passed**, {matched[2]} slow test deselected,",
            f"{matched[3]} existing warnings; Ruff/format and strict mypy pass. Synthetic",
            "observations and rolled-back real PostgreSQL; they establish software behavior only.",
            "",
            "Actual preflight: normal NSE session closed on Sunday2026-10-18; new working-tree",
            "changes are uncommitted. Preflight collected zero observations or fills.",
            "A clean-source open-session run must measure public-feed freshness, operator kill and",
            "actual process-stop/recovery. Trials and the same-date comparison remain open.",
            "See `docs/guides/NSE_PAPER_RECOVERY.md` for run/recovery commands and limits.",
            "",
            "Acceptance requirements remain unresolved; fifth semester is incomplete.",
        ]
    )
    output.with_suffix(".md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--round", type=Path, required=True)
    parser.add_argument("--tests", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report(args.round, args.tests, args.output)
