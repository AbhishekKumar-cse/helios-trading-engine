"""Summarize measured NSE research only after all frozen rounds are complete."""

import json
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from helios.common.db import get_engine  # noqa: E402
from helios.common.lineage import PROJECT_ROOT  # noqa: E402
from helios.data.equities import sha256  # noqa: E402
from helios.equities.pipeline import registry_fingerprint  # noqa: E402
from helios.sim.metrics import return_metrics  # noqa: E402


def main():
    root = PROJECT_ROOT / "reports_out/equity_research"
    names = ("nse_hourly_round1", "nse_hourly_reference", "nse_hourly_round2", "nse_minute_round1")
    rounds = {}
    for name in names:
        directory = root / name
        value = json.loads((directory / "summary.json").read_text())
        assert sha256(directory / "protocol.json") == value["protocol_sha256"]
        assert value["crypto_unchanged"] and value["test_accesses"] == value["promoted"] == 0
        rounds[name] = value
    reference = rounds[names[0]]["registry_before"]
    assert registry_fingerprint(get_engine()) == reference
    assert all(s["registry_before"] == s["registry_after"] == reference for s in rounds.values())
    rows = [row for summary in rounds.values() for row in summary["results"]]
    assert len({row["run_id"] for row in rows}) == len(rows)
    assert not any(all(row["gates"].values()) for row in rows)
    assert all(not row["gates"]["G7"] for row in rows)
    evidence = {}
    for row in rows:
        artifact = Path(row["artifact"])
        assert sha256(artifact) == row["artifact_sha256"]
        if row["symbol"] == "RELIANCE":
            evidence[row["run_id"]] = json.loads(artifact.read_text())
    minute = {r["candidate"]: r for r in rounds["nse_minute_round1"]["results"]}
    hourly = {
        r["candidate"]: r
        for name in names[:-1]
        for r in rounds[name]["results"]
        if r["symbol"] == "RELIANCE"
    }
    comparison, costs = [], []
    for candidate in sorted(minute):
        m, h = evidence[minute[candidate]["run_id"]], evidence[hourly[candidate]["run_id"]]
        if not m["series"] or not h["series"]:
            comparison.append(
                dict(
                    candidate=candidate,
                    status="NOT_RANKABLE",
                    common_days=0,
                    hourly_status=h["status"],
                    minute_status=m["status"],
                )
            )
            continue
        ms, hs = ({p["day"]: p["net_return"] for p in value["series"]} for value in (m, h))
        common = sorted(ms.keys() & hs.keys())
        comparison.append(
            dict(
                candidate=candidate,
                status="CONDITIONAL_DIAGNOSTIC",
                common_days=len(common),
                first_day=common[0],
                last_day=common[-1],
                hourly=asdict(return_metrics([hs[d] for d in common], periods_per_year=252)),
                minute=asdict(return_metrics([ms[d] for d in common], periods_per_year=252)),
                hourly_mean_daily_return=float(np.mean([hs[d] for d in common])),
                minute_mean_daily_return=float(np.mean([ms[d] for d in common])),
            )
        )
        openings_frame = pd.read_parquet(root / "nse_minute_round1/inputs/RELIANCE.parquet")
        openings = {int(r.open_time): Decimal(str(r.open)) for r in openings_frame.itertuples()}
        with localcontext() as context:
            context.prec = 100
            gross, fees, slippage, notional = (Decimal(0) for _ in range(4))
            for fill in m["fills"]:
                quantity, price, fee = (Decimal(fill[k]) for k in ("quantity", "price", "fee"))
                sign = 1 if fill["side"] == "BUY" else -1
                opening = openings[fill["timestamp"]]
                gross -= sign * quantity * opening
                slippage += sign * quantity * (price - opening)
                fees += fee
                notional += quantity * price
            capital = Decimal(m["protocol"]["policy"]["capital"])
            net = sum(p["net_return"] for p in m["series"])
            assert abs(float((gross - fees - slippage) / capital) - net) < 1e-10
            assert abs(fees - Decimal(m["fees_total_inr"])) < Decimal("1e-9")
            stress = sum(m["stress_session_returns"])
            costs.append(
                dict(
                    candidate=candidate,
                    sessions=len(m["series"]),
                    gross_return_before_fee_and_slippage=float(gross / capital),
                    fees_return=float(fees / capital),
                    slippage_return=float(slippage / capital),
                    base_net_return=net,
                    doubled_cost_net_return=stress,
                    fills=len(m["fills"]),
                    fees_inr=str(fees),
                    slippage_inr=str(slippage),
                    traded_notional_inr=str(notional),
                    cost_drag_bps_per_executed_notional=float((fees + slippage) / notional * 10000)
                    if notional
                    else None,
                )
            )
    output = PROJECT_ROOT / "docs/research/nse_equity_closeout_20261018.json"
    assert not output.exists(), "retain prior derived review; use a new version"
    result = dict(
        version="nse_equity_closeout_review_v1",
        reviewed_at=datetime.now(UTC).isoformat(),
        decision="SKIPPED_NO_ELIGIBLE_CANDIDATES",
        eligible_candidates=0,
        promoted=0,
        test_accesses=0,
        review_only=True,
        registry_selection_mutations=False,
        attempts=len(rows),
        statuses=dict(Counter(r["status"] for r in rows)),
        rounds={
            name: dict(
                summary_sha256=sha256(root / name / "summary.json"),
                attempts=len(value["results"]),
                statuses=dict(Counter(r["status"] for r in value["results"])),
                symbols=len({r["symbol"] for r in value["results"]}),
                distinct_definitions=len({r["candidate"] for r in value["results"]}),
            )
            for name, value in rounds.items()
        },
        crypto_registry_unchanged=reference,
        matched_reliance_daily_comparison=comparison,
        minute_reliance_cost_attribution=costs,
        gross_definition="Same quantities as retained base fills, valued at observed opens; "
        "not an independently rerun zero-cost strategy.",
        source_limits=[
            "Current roster is not historical membership; corporate actions unverified.",
            "Complete sessions selected ex-post; special sessions excluded.",
            "Costs/slippage are proxies, not a verified dated tariff/spread.",
            "Hourly/minute vendors and feature windows differ; no causal superiority claim.",
        ],
        known_post_freeze_difference=(
            "The archived minute Bar record retains a legacy yahoo_nse source tag; "
            "the protocol, hashed input bytes and result provenance identify Upstox. "
            "The current code corrects the tag. Frozen artifacts and prices were not edited."
            " Current simulator code also reuses compiled Pydantic validators; "
            "constraints are unchanged. One retained minute session reproduced all "
            "financial fills and ledger snapshots at base and 2x costs exactly; see "
            "nse_validation_cache_parity_20261018.json. Frozen rounds use original code."
        ),
        experiment_rows=rows,
    )
    with output.open("x") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
    labels = [r["candidate"].replace("_", "\n") for r in costs]
    x = np.arange(len(labels))
    fig, ax = plt.subplots(figsize=(13, 5), layout="constrained")
    ax.bar(
        x - 0.25,
        [100 * r["gross_return_before_fee_and_slippage"] for r in costs],
        0.25,
        label="Gross on retained base fills",
        color="#4f8198",
    )
    ax.bar(
        x,
        [100 * r["base_net_return"] for r in costs],
        0.25,
        label="Base 15 + 5 bps per side",
        color="#b4554a",
    )
    ax.bar(
        x + 0.25,
        [100 * r["doubled_cost_net_return"] for r in costs],
        0.25,
        label="Observed 2x cost replay",
        color="#713b45",
    )
    ax.axhline(0, color="#333333", lw=0.7)
    ax.set_xticks(x, labels, fontsize=8)
    ax.set_ylabel("Sum of independent daily returns percent")
    ax.set_title("RELIANCE minute research cost attribution")
    ax.legend(loc="best", fontsize=9)
    ax.grid(axis="y", alpha=0.15)
    ax.set_axisbelow(True)
    fig.savefig(output.with_suffix(".svg"))
    plt.close(fig)
    lines = [
        "# NSE equity research closeout review",
        "",
        "Measured review only. No promotion, TEST access or selection-row mutation.",
        "",
        "| Round | Attempts | Status counts |",
        "|---|---:|---|",
    ]
    for name, value in result["rounds"].items():
        lines.append(f"| {name} | {value['attempts']} | {value['statuses']} |")
    lines += [
        "",
        "All twelve hourly hypothesis types were tested across the 50-company cohort. "
        "The minute model used all 50 stocks for TRAIN, while its twelve execution "
        "attempts used RELIANCE only.",
        "",
        "## Cost attribution",
        "",
        "![Measured cost comparison](nse_equity_closeout_20261018.svg)",
        "",
        "The chart sums independent flat-to-flat daily returns on fixed per-session capital. "
        "It is not a compounded, self-financing multi-day account. Both cost points are "
        "actual shared-engine replays. Gross values retain the base executed quantities; "
        "they are not a zero-cost strategy rerun. ML is omitted from the plot when INVALID; "
        "it is never plotted as a measured zero-return strategy.",
        "",
        "## Matched daily comparison",
        "",
        "| Candidate | Common days | Hourly daily Sharpe | Minute daily Sharpe |",
        "|---|---:|---:|---:|",
    ]
    for row in comparison:
        lines.append(
            f"| {row['candidate']} | {row['common_days']} | "
            f"{row.get('hourly', {}).get('annual_sharpe', 'N/A')} | "
            f"{row.get('minute', {}).get('annual_sharpe', 'N/A')} |"
        )
    lines += [
        "",
        "Metrics use only each pair's common observed dates and 252 sessions/year. "
        "Vendors, clock windows and conditional missing-session cohorts differ. "
        "This is a diagnostic, not a tradable ranking or evidence of frequency superiority.",
        "",
        "## Decision and limits",
        "",
        "SKIPPED_NO_ELIGIBLE_CANDIDATES. G7 remains false for every attempt; TEST stays sealed. "
        "The registry retains all failed and INVALID measurements. A no-eligible review "
        "cannot replace the required actual PAPER trial without a recorded supervisor "
        "scope decision.",
        "",
        result["known_post_freeze_difference"],
        "",
        "Infrastructure interruption/recovery records and immutable driver copies live "
        "beside each affected round. Computed artifacts were recovered without replay, "
        "with unknown runtime left NULL. No original result was overwritten.",
        "",
        "See the companion JSON for all results, fingerprints, exact cost attribution "
        "and matched-date measurements, and the completion assessment/carryover for "
        "outstanding operational requirements.",
    ]
    output.with_suffix(".md").write_text("\n".join(lines) + "\n")
    print(output)


if __name__ == "__main__":
    main()
