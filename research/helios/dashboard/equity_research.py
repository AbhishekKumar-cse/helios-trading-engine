"""Read-only equity alpha research outcomes and shared-engine fill evidence."""

import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from helios.common.lineage import PROJECT_ROOT
from helios.data.equities import sha256


def verified_round(path: Path) -> dict[str, Any]:
    if path.name == "outcomes.jsonl":
        protocol = json.loads((path.parent / "protocol.json").read_text())
        registered = json.loads((path.parent / "preregistration.json").read_text())
        allowed = {
            (r["symbol"], r["candidate"], r["experiment_id"], r["alpha_id"])
            for r in registered["attempts"]
        }
        # The writer appends one outcome after persistence. Ignore only a final
        # incomplete line read concurrently with that append.
        data = path.read_text()
        lines = data.splitlines() if data.endswith("\n") else data.splitlines()[:-1]
        rows = [json.loads(line) for line in lines]
        if (
            protocol["test_access"]
            or any(
                (r["symbol"], r["candidate"], r["experiment_id"], r["alpha_id"]) not in allowed
                for r in rows
            )
            or len({r["run_id"] for r in rows}) != len(rows)
        ):
            raise ValueError("in-progress outcome identity mismatch")
        return dict(
            results=rows,
            interval=protocol["policy"]["interval"],
            partial=True,
            test_accesses="sealed by protocol; final audit pending",
            promoted=0,
        )
    report: dict[str, Any] = json.loads(path.read_text())
    if sha256(path.parent / "protocol.json") != report["protocol_sha256"]:
        raise ValueError("research round protocol changed")
    return report


def render_equity_research(symbol: str) -> None:
    st.subheader("Alpha research · shared engine")
    for directory in sorted((PROJECT_ROOT / "reports_out/equity_research").glob("nse_*")):
        if (directory / "summary.json").exists() or not (
            directory / "preregistration.json"
        ).exists():
            continue
        registered = json.loads((directory / "preregistration.json").read_text())
        outcomes = directory / "outcomes.jsonl"
        completed = len(outcomes.read_text().splitlines()) if outcomes.exists() else 0
        st.info(
            f"Research unfinished · {directory.name} · "
            f"{completed}/{len(registered['attempts'])} attempts retained"
        )
    root = PROJECT_ROOT / "reports_out/equity_research"
    paths = sorted(
        [
            *root.glob("*/summary.json"),
            *(
                path
                for path in root.glob("*/outcomes.jsonl")
                if not (path.parent / "summary.json").exists()
            ),
        ],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not paths:
        st.info("The preregistered equity research round has not completed yet.")
        return
    verified = []
    for path in paths:
        try:
            if any(row["symbol"] == symbol for row in verified_round(path)["results"]):
                verified.append(path)
        except (OSError, ValueError, KeyError):
            st.error(f"Research round {path.parent.name} failed integrity verification.")
    paths = verified
    if not paths:
        st.info("No completed research attempts for this company yet.")
        return
    st.button("Refresh research results")
    st.caption("Refresh reads persisted results; it does not rerun experiments.")
    selected = st.selectbox(
        "Research round",
        paths,
        format_func=lambda path: (
            path.parent.name + (" · running" if path.name == "outcomes.jsonl" else "")
        ),
    )
    try:
        report = verified_round(selected)
    except (OSError, ValueError, KeyError):
        st.error("The research round could not be verified.")
        return
    st.caption(
        "Formula / TRAIN-only calibrated ML → strategy → risk → OMS → simulated venue → "
        "INR ledger → costs / stress → gates → registry."
    )
    if report.get("partial"):
        st.info(
            "Retained attempts from an unfinished round. "
            "Final source and registry audit is pending."
        )
    calibration_path = selected.parent / "ml/calibration.json"
    try:
        calibration = json.loads(calibration_path.read_text())
        if (
            report.get("calibration_hash")
            and sha256(calibration_path) != report["calibration_hash"]
        ):
            raise ValueError("model calibration changed")
        if (
            sha256(selected.parent / "ml/model.txt") != calibration["model_sha256"]
            or calibration["valid_observations_used_for_fit_or_calibration"]
            or calibration["test_access"]
        ):
            raise ValueError("model training lineage mismatch")
        fit, tail = st.columns(2)
        fit.metric("TRAIN fit samples", f"{calibration['train_samples']:,}")
        tail.metric("Separate TRAIN calibration samples", f"{calibration['calibration_samples']:,}")
        st.caption(
            "Frozen model fitted and calibrated before VALID. "
            "These are training counts, not profitability scores."
        )
    except (OSError, ValueError, KeyError):
        st.error("Model training evidence failed integrity verification.")
        return
    st.caption(
        f"Frequency: {report.get('interval', '1h')} · "
        f"{len(report['results'])} retained attempts in this round"
    )
    st.warning(
        "Development benchmark on complete observed sessions. Missing sessions remain unknown. "
        "Costs are explicit proxies. Current-universe and source limitations block promotion."
    )
    shown = [row for row in report["results"] if row["symbol"] == symbol]
    if not shown:
        st.info("This company has no attempts in the selected research round.")
        return
    st.dataframe(
        pd.DataFrame(
            [
                dict(
                    Candidate=row["candidate"],
                    Status=row["status"],
                    Sharpe=row["sharpe"],
                    Fitness=row["fitness"],
                    Gates=f"{sum(row['gates'].values())}/{len(row['gates'])}",
                    Report=f"?run={row['run_id']}",
                )
                for row in shown
            ]
        ),
        hide_index=True,
        width="stretch",
        column_config={"Report": st.column_config.LinkColumn("Report", display_text="Open report")},
    )
    candidate = st.selectbox("Inspect executions", [row["candidate"] for row in shown])
    entry = next(row for row in shown if row["candidate"] == candidate)
    artifact = Path(entry["artifact"])
    try:
        if sha256(artifact) != entry["artifact_sha256"]:
            raise ValueError("execution evidence changed")
        evidence = json.loads(artifact.read_text())
    except (OSError, ValueError, KeyError):
        st.error("The retained execution evidence failed integrity verification.")
        return
    coverage = evidence["coverage"]
    a, b, c = st.columns(3)
    a.metric("Complete sessions", f"{coverage['complete']} / {coverage['expected']}")
    b.metric("Simulated fills", len(evidence["fills"]))
    c.metric("Fees · INR", f"{float(evidence['fees_total_inr']):,.2f}")
    if evidence["series"]:
        daily = pd.DataFrame(evidence["series"])
        capital = float(evidence["protocol"]["policy"]["capital"])
        daily["Reference equity · INR"] = capital * (1 + daily.net_return.cumsum())
        st.line_chart(daily.set_index("day")[["Reference equity · INR"]], color="#64d6bb")
        st.caption(
            "Arithmetic cumulative P&L on fixed per-session capital; every session finishes flat."
        )
    else:
        st.info("INVALID alpha: no rankable backtest metrics. See the report's recorded reasons.")
    with st.expander("Simulated fill log and excluded sessions"):
        st.dataframe(pd.DataFrame(evidence["fills"]), hide_index=True, width="stretch")
        st.dataframe(pd.DataFrame(coverage["excluded"]), hide_index=True, width="stretch")
    st.caption(
        f"{len(report['results'])} registered attempts · TEST accesses {report['test_accesses']} · "
        f"Promoted {report['promoted']} · Existing crypto evidence preserved"
    )
