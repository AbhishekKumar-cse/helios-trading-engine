"""Publish a compact measured closeout after independent data and round checks."""

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from helios.data.equities import sha256, write_json


def report(round_id: str, output: Path) -> None:
    root = Path("reports_out/equity_research") / round_id
    summary = json.loads((root / "summary.json").read_text())
    protocol = json.loads((root / "protocol.json").read_text())
    snapshot = Path(protocol["source_snapshot"])
    manifest = json.loads((snapshot / "manifest.json").read_text())
    checks_path = Path("docs/research/nse_rebuild_data_checks_20261018.json")
    checks = json.loads(checks_path.read_text())
    verified_path = Path("docs/research/nse_repaired_round_checks_20261018.json")
    verified = json.loads(verified_path.read_text())
    assert checks["manifest_sha256"] == sha256(snapshot / "manifest.json")
    assert verified["protocol_sha256"] == summary["protocol_sha256"]
    assert verified["reference_fee_settlement_verified"]
    assert sha256(root / "protocol.json") == summary["protocol_sha256"]
    assert summary["registry_before"] == summary["registry_after"]
    prior = json.loads(Path("docs/research/nse_equity_closeout_20261018.json").read_text())
    for row in prior["experiment_rows"]:
        assert sha256(Path(row["artifact"])) == row["artifact_sha256"]
    audit = json.loads(
        Path("docs/research/nse_assumption_validation_checks_20261018.json").read_text()
    )
    assert summary["registry_after"] == audit["unchanged_crypto_and_test_fingerprints"]
    tests = Path("reports_out/equity_closeout/nse_rebuild_full_tests.log")
    matched = re.search(r"(\d+) passed, 1 deselected, 15 warnings", tests.read_text())
    assert matched
    logs = [
        tests,
        *[
            Path("reports_out/equity_closeout") / name
            for name in (
                "nse_rebuild_final_lint.log",
                "nse_rebuild_final_format.log",
                "nse_rebuild_final_types.log",
            )
        ],
    ]
    assert "All checks passed!" in logs[1].read_text()
    assert "already formatted" in logs[2].read_text()
    assert "Success: no issues found" in logs[3].read_text()
    public = []
    for directory in (
        Path("reports_out/nse_validation/20261018_rebuild_reference1"),
        Path("data/equities/nifty50_historical/20261018_members_v1"),
    ):
        source_manifest = json.loads((directory / "manifest.json").read_text())
        rows = source_manifest.get("sources", source_manifest.get("files"))
        public.append(
            dict(
                path=str(directory),
                requests=len(rows),
                statuses=dict(Counter(str(r["status"]) for r in rows)),
                manifest_sha256=sha256(directory / "manifest.json"),
            )
        )
    calibration = json.loads((root / "ml/calibration.json").read_text())
    payload = dict(
        version="nse_rebuild_closeout_v1",
        round_id=round_id,
        decision="CONDITIONAL_RESEARCH_COMPLETE_G7_BLOCKED",
        rows=manifest["rows"],
        screened_rows=manifest["eligible_rows"],
        companies=checks["companies"],
        model_companies=len(summary["model_symbols"]),
        sessions=checks["sessions"],
        special_session_bars=checks["special_session_bars"],
        exclusions=checks["session_statuses"],
        outside_membership_minutes_removed=checks["outside_membership_minutes_removed"],
        snapshot=str(snapshot),
        snapshot_manifest_sha256=sha256(snapshot / "manifest.json"),
        protocol_sha256=summary["protocol_sha256"],
        summary_sha256=sha256(root / "summary.json"),
        model_sha256=summary["model_hash"],
        calibration_sha256=summary["calibration_hash"],
        train_samples=calibration["train_samples"],
        calibration_samples=calibration["calibration_samples"],
        results=summary["results"],
        public_collections=public,
        source_and_round_checks=[
            dict(path=str(p), sha256=sha256(p)) for p in (checks_path, verified_path)
        ],
        verification_logs=[dict(path=str(p), sha256=sha256(p)) for p in logs],
        full_tests_passed=int(matched.group(1)),
        slow_test_deselected=1,
        old_result_artifacts_verified=len(prior["experiment_rows"]),
        crypto_registry=summary["registry_after"],
        dirty=summary["dirty"],
        code_commit=summary["source_commit"],
        test_accesses=0,
        promoted=0,
        limitations=[
            "Retrospective conditional membership/availability cohort",
            "Unresolved capital-action units quarantined, not reconstructed",
            "Daily scale screen does not certify minute prices or volumes",
            "Historical brokerage and observed liquidity/slippage unverified",
            "Execution benchmark remains RELIANCE; all screened members feed TRAIN",
            "Actual market-hours PAPER/restart/24-hour/seven-day evidence outstanding",
        ],
    )
    write_json(output.with_suffix(".json"), payload)
    lines = [
        "# NSE historical-cohort rebuild and new research round",
        "",
        "The separate data/software rebuild and conditional research round are complete. "
        "Full source certification, profitable alpha and semester operational exit remain open.",
        "",
        f"Retained **{payload['rows']:,} actual minute bars across {payload['companies']} "
        f"historical companies**; **{payload['screened_rows']:,} bars from "
        f"{payload['model_companies']} companies** pass the research screens. "
        f"Removed {payload['outside_membership_minutes_removed']:,} out-of-membership minutes. "
        "Original v1 files/results are preserved.",
        "",
        f"The reviewed calendar has {checks['full_sessions']} full sessions and "
        f"{checks['short_sessions']} short session. Both Budget weekends and the "
        "60-minute Muhurat session are explicit. Temporary demerged membership is "
        "separate from listing/series availability; dummy values are never traded.",
        "",
        "Provider OHLCV is unchanged. Capital-action histories are quarantined instead "
        "of multiplying rounded adjusted prices into invented historical raw prices. "
        "Every scheduled date has an official daily reference; the fixed 0.2% scale "
        "screen remains weaker than minute/volume certification.",
        "",
        f"New fixed LightGBM fit: **{payload['train_samples']:,} TRAIN samples** and "
        f"**{payload['calibration_samples']:,} separate TRAIN calibration samples**. "
        "No VALID fitting or hyperparameter selection, and no TEST access. "
        "The data cohort remains selected ex-post by its stated quality screens. "
        "Frozen 100-tree/15-leaf model, "
        "seed42; 21-bps approximate entry hurdle. Execution uses dated charge estimates, "
        "order brokerage caps, side-aware stamp and separate day-end STT settlements, "
        "plus the explicit 5bps/side slippage scenario and 2x replay.",
        "",
        "| Candidate | Status | VALID Sharpe |",
        "|---|---|---|",
    ]
    for row in summary["results"]:
        score = "—" if row["sharpe"] is None else f"{row['sharpe']:.6f}"
        lines.append(f"| {row['candidate']} · {row['symbol']} | {row['status']} | {score} |")
    lines += [
        "",
        f"Independent checks reconciled {verified['reconciled_base_fills']:,} base fills "
        f"and {verified['reconciled_base_sessions']:,} candidate/session replays, "
        "including fee settlements, ledger cash and stored metrics/gates. "
        f"All {payload['old_result_artifacts_verified']} previous result artifacts retain "
        "their original hashes. Crypto registry remains 25 definitions/34 results; TEST0.",
        "",
        f"Verification: **{payload['full_tests_passed']:,} tests passed**, one existing slow "
        "test excluded; strict types and Ruff pass. Development dirty lineage is "
        "retained when the implementation is subsequently published. Publication "
        "does not relabel the frozen research as a clean-source run.",
        "",
        "G7 remains blocked. Still needed: certified raw share-unit/action/volume "
        "history for excluded observations, observed execution/liquidity/outage policy, "
        "market-hours PAPER acceptance and restart reconciliation, actual24h/7day "
        "trials and same-date comparison, and team evidence.",
        "",
        "Open the [local lab](http://localhost:8501/?page=equities) and choose "
        "Rebuilt historical cohort. The original experiments remain selectable. "
        "See [ADR010](../decisions/ADR-010-nse-source-rebuild.md), "
        "[reproduction guide](../guides/NSE_REBUILD.md) and the companion JSON "
        "for exact paths, hashes, outcomes and exclusions.",
        "",
    ]
    with output.with_suffix(".md").open("x") as handle:
        handle.write("\n".join(lines))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("round_id")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    report(args.round_id, args.output)
