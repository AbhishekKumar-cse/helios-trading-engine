"""Publish a compact review; detailed price/event evidence stays outside Git."""

import argparse
import json
import math
from collections import Counter
from decimal import Decimal
from pathlib import Path

from helios.common.lineage import PROJECT_ROOT
from helios.data.equities import sha256, write_json


def report(audit_path: Path, output: Path) -> None:
    audit = json.loads(audit_path.read_text())
    assert audit["version"] == "nse_assumption_audit_v1"
    # This prose is a review of this measured run, not a generic template with fixed claims.
    assert audit["companies"] == 50 and audit["reference_statuses"] == {"200": 106, "404": 1}
    assert audit["action_kinds"] == {"capital_or_other": 14, "dividend": 110}
    assert audit["price_comparison_counts"] == {
        "NO_LARGE_SCALE_SHIFT_DETECTED": 1965,
        "NO_RETAINED_MINUTES": 100,
        "PRICE_SCALE_REVIEW": 135,
    }
    assert audit["registry_before"] == audit["registry_after"] and audit["test_accesses"] == 0
    canonical = json.loads(
        (PROJECT_ROOT / "docs/research/nse_equity_closeout_20261018.json").read_text()
    )
    summary_path = PROJECT_ROOT / "reports_out/equity_research/nse_minute_round1/summary.json"
    assert sha256(summary_path) == canonical["rounds"]["nse_minute_round1"]["summary_sha256"]
    expected_artifacts = {r["run_id"]: r["artifact_sha256"] for r in canonical["experiment_rows"]}
    assert all(
        expected_artifacts[r["run_id"]] == r["artifact_sha256"] for r in audit["charge_diagnostics"]
    )
    if output.with_suffix(".json").exists() or output.with_suffix(".md").exists():
        raise ValueError("review already exists; choose a new version")
    scales = [r for r in audit["price_comparisons"] if r["status"] == "PRICE_SCALE_REVIEW"]
    observed = [r for r in audit["price_comparisons"] if "official_high" in r]
    assert len(observed) == 2100
    assert all(
        all(
            math.isfinite(r[k]) and r[k] > 0
            for k in ("official_high", "official_low", "minute_high", "minute_low")
        )
        for r in observed
    )
    membership = [r for r in audit["company_rows"] if r["known_preinclusion_minutes"]]
    short = sum(sum(r["retained_short_sessions"].values()) for r in audit["company_rows"])
    summary = {
        k: audit[k]
        for k in (
            "version",
            "audited_at",
            "decision",
            "g7_relaxed",
            "code_commit",
            "code_dirty",
            "runtime_archive",
            "runtime_manifest_sha256",
            "audit_source_sha256",
            "facts_sha256",
            "snapshot_manifest_sha256",
            "references_manifest_sha256",
            "supplement_manifest_sha256",
            "raw_months_verified",
            "companies",
            "total_minute_rows",
            "reference_statuses",
            "action_events",
            "action_kinds",
            "known_preinclusion_minutes",
            "known_missing_historical_members",
            "calendar",
            "price_comparison_counts",
            "charge_diagnostics",
            "registry_before",
            "registry_after",
            "source_snapshot_modified",
            "research_results_modified",
            "test_accesses",
            "limitations",
        )
    }
    summary.update(
        full_audit_path=str(audit_path.resolve().relative_to(PROJECT_ROOT)),
        full_audit_sha256=sha256(audit_path),
        known_preinclusion_by_company={
            r["symbol"]: r["known_preinclusion_minutes"] for r in membership
        },
        price_scale_flags_by_company=dict(Counter(r["symbol"] for r in scales)),
        historical_isin_review_comparisons=sum(
            r.get("identity") != "ISIN" for r in audit["price_comparisons"]
        ),
        reported_corporate_action_isin_mismatches=sum(
            not r["snapshot_isin_matches_reported"] for r in audit["corporate_events"]
        ),
        event_announcement_availability_not_verified=sum(
            not r["point_in_time_availability_verified"] for r in audit["corporate_events"]
        ),
        short_session_minutes_retained=short,
        verified_historical_broker_account_tariff=False,
        execution_slippage_verified=False,
        post_run_nonfinite_guard_checked_rows=len(observed),
        source_urls={
            k: r["url"]
            for k, r in audit["source_reference_records"].items()
            if not k.startswith(("bhav_", "actions_"))
        },
    )
    lines = [
        "# NSE data and trading assumption validation",
        "",
        "The audit is complete. The frozen source is **not ready for a validated historical "
        "Nifty research claim**. Membership, share units and session treatment require a new "
        "versioned dataset and protocol. Existing conditional research remains unchanged; "
        "G7 is not relaxed and TEST stays sealed.",
        "",
        f"Verified all {audit['raw_months_verified']} retained monthly response hashes and "
        f"{audit['companies']} Parquets containing {audit['total_minute_rows']:,} minute bars. "
        "The audit used 107 new public reference requests: 106 succeeded and one dated "
        "bhavcopy returned 404 on an exchange holiday. All 50 corporate-action requests "
        "succeeded. No credentials or new TEST prices were used.",
        "",
        "## Historical membership",
        "",
        "| Current symbol | Documented effective inclusion | Earlier retained minutes |",
        "|---|---|---:|",
    ]
    for row in membership:
        rule = row["known_inclusion_rule"]
        url = summary["source_urls"][rule["reference"]]
        lines.append(
            f"| {row['symbol']} | [{rule['effective']}]({url}) | "
            f"{row['known_preinclusion_minutes']:,} |"
        )
    lines += [
        "",
        f"At least **{audit['known_preinclusion_minutes']:,} source minutes** precede these "
        "documented inclusions. This is a count of raw source rows, not a count of model "
        "training samples or a proof that every other row has correct membership. The "
        "ZOMATO/ETERNAL alias was checked against actual official daily ISIN records.",
        "",
        "Known historical members missing from the current-company snapshot include "
        "WIPRO, HEROMOTOCO, INDUSINDBK, BPCL and BRITANNIA. Temporary demerged constituents "
        "also require treatment. The four retained review notices are evidence of known "
        "changes; they do not establish a complete daily point-in-time membership history.",
        "",
        "## Corporate actions and price units",
        "",
        f"The NSE returned {audit['action_events']} events: 110 dividend entries and "
        "14 capital/other entries. Historical ISIN fields differ from the current roster "
        f"in {summary['reported_corporate_action_isin_mismatches']} event records. "
        "Ex-dates alone do not establish when a trading process knew an announcement; "
        "the audit does not backdate their availability.",
        "",
        "44 dated exchange daily files gave 2,200 company/date comparisons. Of these, "
        "100 have no retained minutes on the two excluded Budget dates, and 135 flag a "
        "large same-direction difference in both high and low prices. The other 1,965 "
        "have no large scale shift under the declared 5% screen; this is not full price, "
        "volume or executable-liquidity certification.",
        "",
        "| Company | Sampled price-scale flags |",
        "|---|---:|",
    ]
    for symbol, count in summary["price_scale_flags_by_company"].items():
        lines.append(f"| {symbol} | {count} |")
    lines += [
        "",
        "For example, sampled BAJFINANCE highs/lows before its June 2025 capital action "
        "are about one tenth of the official contemporary daily prices. This is consistent "
        "with later split/bonus adjustment, an inference supported by the separate event "
        "records. Current share units cannot silently stand in for the historical whole "
        "shares used to allocate INR capital. Do not rescale on a ratio screen alone. "
        "Official closing-price benchmarks and last-minute closes also differ in definition.",
        "",
        "## Market sessions",
        "",
        "The reviewed calendar contains 366 normal weekday full sessions and two additional "
        "full Budget sessions across the source range. Their actual raw responses contain "
        "18,750 candles per date across 50 companies; neither date survived the original "
        "weekday filter. Existing results explicitly used normal sessions, so their old "
        "coverage statement must retain that scope.",
        "",
        "[2025 Budget session](https://nsearchives.nseindia.com/content/circulars/CMTR65729.pdf), "
        "[2026 Budget session](https://nsearchives.nseindia.com/content/circulars/CMTR72349.pdf). "
        f"The retained TRAIN source also has {short:,} minutes from the one-hour "
        "[2025 Muhurat session](https://nsearchives.nseindia.com/content/circulars/CMTR70319.pdf). "
        "A new calendar must give this session its actual 13:45–14:45 window and 60 slots. "
        "It must not treat it as an ordinary 375-slot session.",
        "",
        "## Explicit charge diagnostic",
        "",
        "Added a Decimal charge estimator for same-day flat NSE cash-equity trades. It "
        "caps brokerage across partial fills of each order, applies buy-side stamp duty, "
        "daily security-VWAP STT with client-day rupee rounding, SEBI charges and GST. "
        "The exchange/IPFT components follow their dated circulars. The combined outflow "
        "is unchanged by the March 2026 reclassification; the components must not be "
        "double-counted.",
        "",
        "The brokerage scenario uses the current public Zerodha tariff; it is not a "
        "verified historical account contract. Non-STT invoice rounding and contract-note "
        "reconciliation remain open. No delivery, overnight, auto-square-off, funding or "
        "real-money execution is claimed. Slippage remains an unverified 5-bps scenario.",
        "",
        "| Retained minute formula | Old flat commission/tax INR | Reference charge estimate INR |",
        "|---|---:|---:|",
    ]
    for row in audit["charge_diagnostics"]:
        lines.append(
            f"| {row['candidate']} | {Decimal(row['actual_base_proxy_fees_inr']):,.2f} | "
            f"{Decimal(row['reference_charge_estimate']['total']):,.2f} |"
        )
    lines += [
        "",
        "These are charge comparisons on the exact retained fills, not new backtests, "
        "model fits, candidate rankings or claims of profitable performance. Applying a "
        "different fee table to old quantities cannot fix membership, share-unit, "
        "liquidity or causal-outage assumptions.",
        "",
        "Primary references: [NSE levies](" + summary["source_urls"]["nse_levies"] + "), "
        "[2024 exchange rates](" + summary["source_urls"]["exchange_cost_20241001"] + "), "
        "[March 2026 reclassification](" + summary["source_urls"]["exchange_cost_20260301"] + "), "
        "[public brokerage](https://zerodha.com/charges/), "
        "[NSE STT methodology](https://nsearchives.nseindia.com/content/circulars/cmtr5588.htm). "
        "Historical rates in the 2004 methodology circular are not used as current rates.",
        "",
        "## Required rebuild before further performance research",
        "",
        "1. Reconstruct effective-date membership and identity history, including missing "
        "and temporary constituents; collect only permitted TRAIN/VALID prices for that universe.",
        "2. Establish historical raw share units, action factors and volume treatment against "
        "exchange evidence. Preserve adjusted prices separately and keep availability explicit.",
        "3. Derive a new snapshot from retained raw bytes with versioned full and short sessions. "
        "Report missing observations; do not overwrite or fill the old snapshot.",
        "4. Integrate an explicitly versioned, side/order/day-aware fee policy into new "
        "execution runs, with accepted billing/rounding rules and independent fill checks. "
        "Keep observed spread/impact and outage management as separate acceptance requirements.",
        "5. Preregister a new research round after the source/protocol checks pass. Retrain "
        "on TRAIN only; retain failures and keep TEST sealed until authorized selection.",
        "",
        "## Retained evidence",
        "",
        "The compact companion JSON records counts, charge breakdowns, source hashes "
        "and archive location. The detailed audit, corporate events and daily comparisons "
        "remain local at `"
        + summary["full_audit_path"]
        + "` (SHA-256 `"
        + summary["full_audit_sha256"]
        + "`). "
        "Raw references are in `reports_out/nse_validation/20261018_reference1` and "
        "`20261018_supplement1`. All 900 original monthly files and 50 source Parquets "
        "were checked read-only. Crypto fingerprints remain 25 definitions/34 results "
        "and TEST access is zero. No result, gate or source snapshot was overwritten.",
        "",
        "After the audit, the comparison parser gained a fail-closed check for nonfinite "
        "official prices. All 2,100 observed-minute comparisons satisfy it; no measured "
        "value changed. The original audit runtime remains archived separately.",
        "",
    ]
    write_json(output.with_suffix(".json"), summary)
    with output.with_suffix(".md").open("x", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    print(output.with_suffix(".md"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audit", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    report(args.audit, args.output)
