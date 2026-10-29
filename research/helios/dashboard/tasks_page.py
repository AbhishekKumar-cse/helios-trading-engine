"""Inspectable durable jobs and their hash-checked development receipts."""

import json
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

from helios.common.lineage import PROJECT_ROOT
from helios.dashboard.lab_store import cancel, interrupt_stale, jobs
from helios.dashboard.lab_worker import start_worker
from helios.dashboard.workstation_data import read_account
from helios.dashboard.workstation_shell import navigate


def render_account(account: dict[str, Any]) -> None:
    protocol, result = account["protocol"], account["result"]
    base = result["scenarios"]["1"]
    stress = result["scenarios"].get("2")
    columns = st.columns(5)
    for column, label, value in zip(
        columns,
        ("Net return", "Doubled costs", "Sharpe · session returns", "Fill legs", "Fees / INR"),
        (
            f"{base['summary']['net_return']:.2%}",
            f"{stress['summary']['net_return']:.2%}" if stress else "Not measured",
            f"{base['summary']['sharpe']:.2f}"
            if base["summary"]["sharpe"] is not None
            else "Undefined",
            base["summary"]["fills"],
            f"{float(base['summary']['fees']):,.2f}",
        ),
        strict=True,
    ):
        column.metric(label, value)
    performance, gates, fills, evidence = st.tabs(
        ["Performance", "Research checks", "Fills", "Evidence"]
    )
    with performance:
        curves: list[dict[str, Any]] = []
        for multiplier, scenario in result["scenarios"].items():
            curves.extend(
                dict(
                    Time=pd.to_datetime(point["timestamp"], unit="us", utc=True),
                    Equity=float(point["equity"]),
                    Scenario="Normal costs" if multiplier == "1" else "Doubled costs",
                )
                for point in scenario["equity"]
            )
        if curves:
            chart = (
                alt.Chart(pd.DataFrame(curves))
                .mark_line(point=True)
                .encode(
                    x=alt.X("Time:T"),
                    y=alt.Y("Equity:Q", title="Equity / INR", scale=alt.Scale(zero=False)),
                    color=alt.Color(
                        "Scenario:N",
                        scale=alt.Scale(
                            domain=["Normal costs", "Doubled costs"],
                            range=["#828fff", "#f4b86a"],
                        ),
                    ),
                    tooltip=["Time:T", "Scenario:N", alt.Tooltip("Equity:Q", format=",.2f")],
                )
                .properties(height=280)
            )
            st.altair_chart(chart, width="stretch")
        daily = pd.DataFrame(
            [
                {
                    "Session": row["day"],
                    "Start cash / INR": float(row["start_cash"]),
                    "End cash / INR": float(row["end_cash"]),
                    "Net P&L / INR": float(row["net_pnl"]),
                    "Return %": row["net_return"] * 100,
                    "Fees / INR": float(row["fees"]),
                    "Fill legs": row["fills"],
                }
                for row in base["daily"]
            ]
        )
        st.dataframe(
            daily,
            hide_index=True,
            width="stretch",
            column_config={
                name: st.column_config.NumberColumn(format="%.2f")
                for name in daily.columns
                if name not in {"Session", "Fill legs"}
            },
        )
        if protocol.get("excluded_sessions"):
            st.warning(
                f"{len(protocol['excluded_sessions'])} expected sessions excluded; "
                "no prices or returns invented."
            )
    with gates:
        st.info("Development account · formal eligibility not assessed")
        st.dataframe(
            pd.DataFrame(
                [
                    dict(
                        Check="Shared replay / simulated fills",
                        Status="Measured",
                        Evidence="Retained orders, fills and ledger snapshots",
                    ),
                    dict(
                        Check="Normal and doubled costs",
                        Status="Measured" if stress else "Incomplete",
                        Evidence="Independent frozen cost scenarios",
                    ),
                    dict(
                        Check="Source / execution certification",
                        Status="Required",
                        Evidence="Public NSE development inputs remain conditional",
                    ),
                    dict(
                        Check="Unseen validation and formal gates",
                        Status="Not assessed",
                        Evidence="This sandbox does not promote or write alpha registry results",
                    ),
                ]
            ),
            hide_index=True,
            width="stretch",
        )
    with fills:
        if base["fills"]:
            table = pd.DataFrame(base["fills"])
            st.dataframe(table, hide_index=True, width="stretch")
            st.download_button(
                "Download fills CSV",
                table.to_csv(index=False),
                "development_fills.csv",
                "text/csv",
                key="fills_" + protocol["run_id"],
            )
        else:
            st.info("No simulated fills in this account.")
    with evidence:
        st.code(account["path"].relative_to(PROJECT_ROOT).as_posix(), language=None)
        st.json(protocol, expanded=False)
        st.download_button(
            "Download retained result JSON",
            json.dumps(result, indent=2),
            "development_result.json",
            "application/json",
            key="result_" + protocol["run_id"],
        )


@st.fragment(run_every=3)
def _live_tasks() -> None:
    rows = jobs(PROJECT_ROOT)
    a, b, c = st.columns([1, 1, 2])
    if a.button(
        "Start queued jobs",
        type="primary",
        width="stretch",
        disabled=not any(r["status"] == "QUEUED" for r in rows)
        or any(r["status"] == "RUNNING" for r in rows),
        icon=":material/play_arrow:",
    ):
        start_worker(PROJECT_ROOT)
        st.info("Worker requested. The matrix shows a job only after its database claim.")
    if b.button("New experiment", width="stretch"):
        navigate("Template Lab")
        st.rerun()
    c.caption(
        "One worker processes at most 12 jobs and exits after an idle wait. "
        "This page refreshes every 3 seconds."
    )
    columns = st.columns(4)
    for column, label, states in zip(
        columns,
        ("Queued", "Running · one local slot", "Completed", "Failed / interrupted"),
        ({"QUEUED"}, {"RUNNING"}, {"COMPLETED"}, {"FAILED", "INTERRUPTED"}),
        strict=True,
    ):
        column.metric(label, sum(row["status"] in states for row in rows))
    if not rows:
        st.info("No tasks yet. Add a reviewed experiment from Template Lab.")
        st.button(
            "Open Template Lab", on_click=navigate, args=("Template Lab",), key="tasks_empty_lab"
        )
        return
    task_tab, matrix = st.tabs(["Tasks", "Execution matrix"])
    with task_tab:
        table = []
        for row in rows:
            spec = json.loads(row["spec_json"])
            table.append(
                dict(
                    Task=row["id"],
                    Company=spec["options"]["symbol"],
                    Frequency=spec["interval"],
                    Status=row["status"],
                    Progress=row["progress"],
                    Lookback=spec["options"]["lookback"],
                    Updated=row["updated_at"],
                )
            )
        st.dataframe(
            pd.DataFrame(table),
            hide_index=True,
            width="stretch",
            height=min(300, 36 * (len(rows) + 1) + 8),
            column_config={
                "Progress": st.column_config.ProgressColumn(
                    min_value=0, max_value=1, format="percent"
                )
            },
        )
    with matrix:
        running = [row for row in rows if row["status"] == "RUNNING"]
        st.subheader("Local execution slot")
        if running:
            row = running[0]
            st.progress(row["progress"], text=row["message"] or "Starting shared replay")
            st.caption(f"{row['id']} · heartbeat {row['heartbeat']} · one bounded worker slot")
        else:
            st.info("Idle · queued work starts only when you run it.")
        st.caption(
            "This slot is a local evaluator process. It is separate from BRAIN "
            "simulation quotas and PAPER operation."
        )
    selected = st.selectbox(
        "Inspect task",
        rows,
        format_func=lambda row: (
            f"{row['id']} · {json.loads(row['spec_json'])['options']['symbol']} · {row['status']}"
        ),
        key="task_inspector",
    )
    spec = json.loads(selected["spec_json"])
    with st.container(border=True):
        st.subheader(spec["options"]["symbol"] + " · " + selected["status"])
        st.write(spec["hypothesis"])
        st.code(spec["options"]["expression"], language=None)
        st.caption(
            f"{spec['interval']} bars · {spec['options']['start']} → "
            f"{spec['options']['end']} · both cost scenarios · development only"
        )
        if selected["status"] in {"QUEUED", "RUNNING"}:
            if st.button("Cancel task", key="cancel_" + selected["id"]):
                cancel(PROJECT_ROOT, selected["id"])
                st.rerun()
            if selected["cancel_requested"]:
                st.info(
                    "Cancellation requested. A running account stops at a completed "
                    "flat-session boundary."
                )
        if selected["message"]:
            st.caption(selected["message"])
        if selected["status"] == "COMPLETED" and selected["result_path"]:
            try:
                account = read_account(PROJECT_ROOT / selected["result_path"])
                if (
                    account["protocol"]["options"] != spec["options"]
                    or account["protocol"]["manifest_sha256"] != spec["manifest_sha256"]
                ):
                    raise ValueError("task/result binding mismatch")
                render_account(account)
            except (OSError, ValueError, KeyError, TypeError):
                st.error(
                    "Retained task result is unavailable or its evidence changed. "
                    "Performance is withheld."
                )
        with st.expander("Frozen experiment"):
            st.json(spec, expanded=False)
            st.caption("Request SHA-256: " + selected["request_hash"])
        if selected["status"] in {"FAILED", "CANCELLED", "INTERRUPTED"}:
            st.caption(
                "Partial receipts, if written, remain in reports_out/research_lab/runs/"
                + selected["id"]
            )


def render_tasks() -> None:
    st.title("Tasks")
    st.caption(
        "Finite development experiments · durable queue · retained outcomes · "
        "no automatic promotion"
    )
    if notice := st.session_state.pop("lab_notice", None):
        st.success(notice)
    _live_tasks()
    with st.expander("Interrupted worker recovery"):
        st.write(
            "After at least 60 seconds without a heartbeat, reconcile running jobs "
            "as interrupted. This preserves partial evidence and never resumes or "
            "requeues them automatically."
        )
        if st.button("Reconcile stale jobs"):
            st.info(f"{interrupt_stale(PROJECT_ROOT)} stale job(s) marked interrupted.")
