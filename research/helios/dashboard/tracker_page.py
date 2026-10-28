"""Spreadsheet-style view of verified local research outcomes, without promotion writes."""

from dataclasses import asdict

import pandas as pd
import streamlit as st

from helios.common.lineage import PROJECT_ROOT
from helios.dashboard.alpha_tracker import refresh_tracker


def render_tracker() -> None:
    st.title("Alpha tracker")
    st.write("See which signal worked on which dataset and stock—and what still needs proof.")
    st.caption(
        "Positive performance is separate from eligibility. This table covers supported official "
        "daily studies and stock-specific candidates. "
        "Crypto/minute registry results remain in Saved results."
    )
    refresh = st.button("Refresh from verified evidence", icon=":material/refresh:")
    if refresh or "alpha_tracker_snapshot" not in st.session_state:
        try:
            st.session_state.alpha_tracker_snapshot = refresh_tracker(PROJECT_ROOT)
        except (OSError, ValueError):
            st.error(
                "The local tracker could not be refreshed. Check its evidence and file access."
            )
            return
    rows, issues = st.session_state.alpha_tracker_snapshot
    for issue in [item for item in issues if "incomplete" not in item]:
        st.warning(issue)
    incomplete = [item for item in issues if "incomplete" in item]
    if incomplete:
        with st.expander(f"Retained incomplete attempts ({len(incomplete)})"):
            for issue in incomplete:
                st.caption(issue)
    if not rows:
        st.info("No verified supported research yet. Refresh after a retained study completes.")
        return
    a, b, c, d = st.columns(4)
    a.metric("Alpha definitions", len({r.alpha for r in rows}))
    b.metric(
        "Stock-specific leads",
        len(
            {
                r.alpha
                for r in rows
                if r.scope.startswith("Single stock")
                and r.normal_return_pct is not None
                and r.doubled_return_pct is not None
                and r.normal_return_pct > 0
                and r.doubled_return_pct > 0
            }
        ),
    )
    c.metric("Eligible", sum(r.eligible for r in rows))
    d.metric("Forward observations", "0 · collection not started")
    left, middle, right = st.columns([2, 2, 1])
    search = left.text_input("Find alpha, stock or dataset", placeholder="Try BSE, peer or cost…")
    dataset = middle.selectbox("Dataset", ["All", *sorted({r.dataset for r in rows})])
    status = right.selectbox(
        "Show", ["All", "Positive both costs", "Forward plans", "Failed screens"]
    )
    fractional = st.checkbox("Include fractional diagnostics", value=False)
    shown = [
        r
        for r in rows
        if (fractional or r.units == "Whole shares")
        and (dataset == "All" or r.dataset == dataset)
        and search.casefold() in f"{r.alpha} {r.stock} {r.dataset}".casefold()
        and (
            status == "All"
            or status == "Positive both costs"
            and r.normal_return_pct is not None
            and r.doubled_return_pct is not None
            and r.normal_return_pct > 0
            and r.doubled_return_pct > 0
            or status == "Forward plans"
            and r.split == "Forward · not started"
            or status == "Failed screens"
            and r.study_screen == "Failed original screen"
        )
    ]
    if not shown:
        st.info("No rows match these filters.")
    else:
        names = dict(
            alpha="Alpha",
            stock="Stock(s)",
            normal_return_pct="Normal %",
            doubled_return_pct="Doubled costs %",
            sharpe="Sharpe",
            performance="Performance",
            dataset="Dataset",
            scope="Scope",
            split="Split",
            units="Units",
            study_screen="Study screen",
            fitness="Fitness",
            trades="Trades",
            eligible="Eligible",
            period="Period",
        )
        table = pd.DataFrame([asdict(r) for r in shown])[list(names)].rename(columns=names)
        st.dataframe(
            table,
            hide_index=True,
            width="stretch",
            height=440,
            column_config={
                "Normal %": st.column_config.NumberColumn(format="%.2f"),
                "Doubled costs %": st.column_config.NumberColumn(format="%.2f"),
                "Sharpe": st.column_config.NumberColumn(format="%.2f"),
                "Fitness": st.column_config.NumberColumn(format="%.2f"),
                "Stock(s)": st.column_config.TextColumn(width="medium"),
                "Dataset": st.column_config.TextColumn(width="medium"),
            },
        )
        selected = st.selectbox(
            "Inspect a record", shown, format_func=lambda r: f"{r.alpha} · {r.scope} · {r.units}"
        )
        with st.container(border=True):
            st.markdown(f"**{selected.alpha}** · {selected.stock}")
            st.write(selected.performance)
            st.write("Next step:", selected.next_step)
            st.caption("Eligibility blockers: " + selected.blockers)
            st.caption("Period: " + selected.period)
            st.code(selected.evidence, language=None)
            st.caption("Evidence SHA-256: " + selected.evidence_sha256)
            st.caption(
                "Dataset SHA-256: "
                + (selected.dataset_sha256 or "No forward dataset collected yet")
            )
    path = PROJECT_ROOT / "local_state/alpha_tracker.csv"
    if path.exists():
        st.download_button(
            "Download tracker CSV", path.read_bytes(), "alpha_tracker.csv", "text/csv"
        )
    st.caption(
        "Local CSV: local_state/alpha_tracker.csv · excluded from Git. "
        "Refresh rebuilds this sheet from evidence; it does not edit results or run trading."
    )
