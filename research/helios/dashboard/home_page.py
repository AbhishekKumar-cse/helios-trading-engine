"""Workstation landing page: actual retained counts and durable work in flight."""

import json

import pandas as pd
import streamlit as st

from helios.common.lineage import PROJECT_ROOT
from helios.dashboard.lab_store import jobs
from helios.dashboard.workstation_data import inventory_snapshot, registry_snapshot
from helios.dashboard.workstation_shell import navigate


def render_home() -> None:
    st.title("Your research, in one workspace.")
    st.caption("Select data. Write a hypothesis. Run a bounded experiment. Inspect the evidence.")
    with st.spinner("Loading retained research…"):
        definitions, attempts, connected = registry_snapshot()
    try:
        inventory, issues = inventory_snapshot()
    except (OSError, ValueError):
        inventory, issues = [], ["Retained dataset inventory unavailable"]
    queued = jobs(PROJECT_ROOT)
    columns = st.columns(4)
    for column, label, value in zip(
        columns,
        ("Retained datasets", "Registered alphas", "Evaluated attempts", "Promoted runs"),
        (
            len(inventory),
            len(definitions) if connected else "Unavailable",
            len(attempts) if connected else "Unavailable",
            sum(row["Status"] == "PROMOTED" for row in attempts) if connected else "Unavailable",
        ),
        strict=True,
    ):
        column.metric(label, value)
    if not connected:
        st.warning("Registry connection unavailable. Counts are not replaced with zero.")
    for issue in issues:
        st.caption(issue)
    st.write("")
    with st.container(border=True):
        left, right = st.columns([4, 1])
        left.subheader("Work in flight")
        right.button("Open Tasks", width="stretch", on_click=navigate, args=("Tasks",))
        active = [row for row in queued if row["status"] in {"QUEUED", "RUNNING"}]
        if active:
            st.dataframe(
                pd.DataFrame(
                    [
                        dict(
                            Task=row["id"],
                            Company=json.loads(row["spec_json"])["options"]["symbol"],
                            Status=row["status"],
                            Progress=f"{row['progress']:.0%}",
                            Updated=row["updated_at"],
                        )
                        for row in active
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
        else:
            st.info("No development jobs running. Your next experiment starts in Template Lab.")
    left, right = st.columns([1.5, 1])
    with left, st.container(border=True):
        st.subheader("Build from retained data")
        st.write(
            "Choose a screened NSE minute or hourly dataset, bind observed fields "
            "and review a finite set of lookbacks before queuing."
        )
        a, b = st.columns(2)
        a.button(
            "Open Template Lab",
            type="primary",
            width="stretch",
            on_click=navigate,
            args=("Template Lab",),
        )
        b.button("Browse Data Explorer", width="stretch", on_click=navigate, args=("Datasets",))
    with right, st.container(border=True):
        st.subheader("Keep the result in context")
        st.write(
            "Positive performance, passed gates and formal eligibility are "
            "separate. Inspect a stock's actual dataset and cost assumptions."
        )
        st.button("Explore Alphas", width="stretch", on_click=navigate, args=("Alpha tracker",))
    st.subheader("Research history")
    if attempts:
        columns = st.columns(3)
        columns[0].metric("Rejected", sum(row["Status"] == "REJECTED" for row in attempts))
        columns[1].metric(
            "Invalid · no ranking", sum(row["Status"] == "INVALID" for row in attempts)
        )
        columns[2].metric("Local development jobs", len(queued))
        with st.expander("Why a run can fail"):
            st.write(
                "INVALID means prerequisites or usable observations failed. REJECTED "
                "means the retained evaluation did not pass its gates. Template Lab "
                "produces separate development accounts and does not promote "
                "candidates."
            )
