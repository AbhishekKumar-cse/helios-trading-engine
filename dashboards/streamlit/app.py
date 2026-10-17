"""Run: python -m streamlit run dashboards/streamlit/app.py --server.address 127.0.0.1"""

import pandas as pd
import streamlit as st

from helios.dashboard.registry import read_registry, report_html


def main() -> None:
    st.set_page_config(
        page_title="HELIOS · Backtesting lab", layout="wide", initial_sidebar_state="collapsed"
    )
    st.sidebar.title("HELIOS")
    st.sidebar.caption("Research & simulated execution")
    default = 1 if st.query_params.get("run") or st.query_params.get("page") == "registry" else 0
    if st.query_params.get("page") == "equities":
        default = 3
    page = st.sidebar.radio(
        "Page",
        ["Simulation", "Alpha registry", "Paper trading", "Nifty 50 equities"],
        index=default,
    )
    st.sidebar.caption(
        "Simulation is ready without a database. Registry and PAPER show retained runs."
    )
    if page == "Simulation":
        from helios.dashboard.simulation_page import render_simulation

        render_simulation()
        return
    if page == "Paper trading":
        from helios.dashboard.paper_page import render_paper

        render_paper()
        return
    if page == "Nifty 50 equities":
        from helios.dashboard.equity_page import render_equities

        render_equities()
        return
    st.caption("HELIOS · BACKTEST RESEARCH · READ ONLY")
    st.title("Alpha registry")
    st.write(
        "Browse registered definitions and retained measurements. "
        "Selection decisions remain separate."
    )

    if run := st.query_params.get("run"):
        st.link_button("Back to registry", "?page=registry")
        try:
            content = report_html(run)
        except Exception:
            st.error("This retained report is unavailable or its evidence could not be verified.")
        else:
            st.download_button(
                "Download verified HTML", content, file_name=f"{run}.html", mime="text/html"
            )
            st.html(content)
        return

    try:
        definitions, attempts = read_registry()
    except Exception:
        st.error("Registry unavailable. Check the local database configuration and connection.")
        return

    left, middle, right = st.columns(3)
    left.metric("Registered versions", len(definitions))
    middle.metric("Retained attempts", len(attempts))
    right.metric("INVALID attempts", sum(a["Status"] == "INVALID" for a in attempts))
    st.caption(
        "INVALID measurements have no performance ranking. "
        "Synthetic definitions are marked explicitly."
    )

    search = st.text_input("Search alpha or name")
    family = st.selectbox("Horizon family", ["All", *sorted({d["Family"] for d in definitions})])
    shown = [
        d
        for d in definitions
        if (family == "All" or d["Family"] == family)
        and search.casefold() in (d["Alpha"] + " " + d["Name"]).casefold()
    ]
    links = {"Report": st.column_config.LinkColumn("Report", display_text="Open report")}
    st.dataframe(pd.DataFrame(shown), hide_index=True, width="stretch", column_config=links)
    st.subheader("Every retained measurement")
    visible = {(d["Alpha"], d["Version"]) for d in shown}
    st.dataframe(
        pd.DataFrame([a for a in attempts if (a["Alpha"], a["Version"]) in visible]),
        hide_index=True,
        width="stretch",
        column_config=links,
    )
    if not definitions:
        st.info("No definitions registered yet.")


if __name__ == "__main__":
    main()
