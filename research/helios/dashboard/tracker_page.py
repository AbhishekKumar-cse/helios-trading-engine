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
        "Registered crypto and NSE attempts, plus audited daily and stock-specific studies. "
        "Each row keeps its original stock, dataset snapshot, split, costs and gates. "
        "Positive performance is separate from eligibility; missing metrics stay blank."
    )
    refresh = st.button("Refresh from verified evidence", icon=":material/refresh:")
    if refresh or "alpha_tracker_snapshot_v2" not in st.session_state:
        try:
            with st.spinner("Verifying retained results and refreshing the local CSV…"):
                st.session_state.alpha_tracker_snapshot_v2 = refresh_tracker(
                    PROJECT_ROOT, include_registry=True
                )
        except (OSError, ValueError):
            st.error(
                "The local tracker could not be refreshed. Check its evidence and file access."
            )
            return
    rows, issues = st.session_state.alpha_tracker_snapshot_v2
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
    d.metric("Retained records", len(rows))
    market_col, frequency_col, origin_col = st.columns(3)
    market = market_col.selectbox("Market", ["All", *sorted({r.market for r in rows})])
    frequency = frequency_col.selectbox("Frequency", ["All", *sorted({r.frequency for r in rows})])
    origin = origin_col.selectbox(
        "Evidence source", ["All", *sorted({r.source_kind for r in rows})]
    )
    left, middle, right = st.columns([2, 2, 1])
    search = left.text_input("Find alpha, stock or dataset", placeholder="Try BSE, peer or cost…")
    dataset = middle.selectbox("Dataset", ["All", *sorted({r.dataset for r in rows})])
    status = right.selectbox(
        "Show",
        [
            "All",
            "Positive both costs",
            "Forward plans",
            "Failed screens",
            "INVALID",
            "REJECTED",
            "DRAFT",
        ],
    )
    fractional = st.checkbox("Include fractional diagnostics", value=False)
    shown = [
        r
        for r in rows
        if (fractional or "fractional" not in r.units.casefold())
        and (market == "All" or r.market == market)
        and (frequency == "All" or r.frequency == frequency)
        and (origin == "All" or r.source_kind == origin)
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
            or status in {"INVALID", "REJECTED", "DRAFT"}
            and r.study_screen == status
        )
    ]
    if not shown:
        st.info("No rows match these filters.")
    else:
        st.caption(
            f"Showing {len(shown)} of {len(rows)} retained records. "
            "Different runs, stocks and snapshots remain separate."
        )
        names = dict(
            alpha="Alpha",
            version="Version",
            market="Market",
            frequency="Frequency",
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
            trade_count_kind="Trade convention",
            eligible="Eligible",
            period="Period",
            source_kind="Evidence source",
            evidence_status="Evidence status",
            run_id="Run ID",
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
            if selected.expression:
                st.code(selected.expression, language=None)
            st.caption(
                f"{selected.market} · {selected.frequency} · "
                f"{selected.source_kind} · {selected.evidence_status}"
            )
            st.write("Next step:", selected.next_step)
            st.caption("Eligibility blockers: " + selected.blockers)
            st.caption("Period: " + selected.period)
            st.code(selected.evidence, language=None)
            st.caption("Evidence SHA-256: " + selected.evidence_sha256)
            st.caption(
                "Dataset SHA-256: "
                + (selected.dataset_sha256 or "No forward dataset collected yet")
            )
            if selected.run_id:
                st.link_button("Open registered run report", f"?run={selected.run_id}")
    with st.expander("Coverage & interpretation"):
        st.write(
            "Registry rows are individual evaluated attempts, not additional independent alphas. "
            "Formal status is retained unchanged. Missing or changed evaluation artifacts "
            "withhold performance; snapshot IDs identify registered inputs "
            "without claiming a new bulk-file certification."
        )
        st.write(
            "Daily exploratory studies use their audited original accounting. Registered NSE "
            "attempts use whole-share session accounting; crypto uses its own frozen units and "
            "costs. These accounts are not a pooled return series. Sandbox demonstrations and "
            "unsupported exploratory formats are not imported as verified trials."
        )
        st.caption(
            "The BSE forward plan remains a plan; this tracker does not start collection "
            "or imply elapsed dates produced observations."
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
