"""Read-only equity alpha research outcomes and shared-engine fill evidence."""

import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from helios.common.lineage import PROJECT_ROOT
from helios.data.equities import sha256


def verified_round(path: Path) -> dict[str, Any]:
    report: dict[str, Any] = json.loads(path.read_text())
    if sha256(path.parent / "protocol.json") != report["protocol_sha256"]:
        raise ValueError("research round protocol changed")
    return report


def render_equity_research(symbol: str) -> None:
    st.subheader("Alpha research · shared engine")
    paths = sorted(
        (PROJECT_ROOT / "reports_out/equity_research").glob("*/summary.json"), reverse=True
    )
    if not paths:
        st.info("The preregistered equity research round has not completed yet.")
        return
    selected = st.selectbox("Research round", paths, format_func=lambda path: path.parent.name)
    try:
        report = verified_round(selected)
    except (OSError, ValueError, KeyError):
        st.error("The research round could not be verified.")
        return
    st.caption(
        "Formula / TRAIN-only calibrated ML → strategy → risk → OMS → simulated venue → "
        "INR ledger → costs / stress → gates → registry."
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
