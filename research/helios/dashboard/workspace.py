"""Shared navigation and visual shell for the local research workspace."""

import streamlit as st

PAGES = {
    "Simulation": ("simulation", "Build & simulate"),
    "Nifty 50 equities": ("equities", "NSE research"),
    "Alpha tracker": ("tracker", "Alpha tracker"),
    "Datasets": ("datasets", "Datasets & fields"),
    "Alpha registry": ("registry", "Saved results"),
    "Paper trading": ("paper", "Paper monitor"),
}

STYLE = """<style>
.stMainBlockContainer{max-width:1540px;padding:1.4rem 1.5rem 3rem}
[data-testid="stHeader"]{background:transparent}
[data-testid="stSidebar"][data-collapsed="false"]{width:230px!important;
min-width:230px!important;max-width:230px!important}
[data-testid="stSidebar"]{
border-right:1px solid #243044;background:#0e1725}
[data-testid="stSidebar"] [data-testid="stVerticalBlock"]{gap:.75rem}
[data-testid="stSidebar"] [role="radiogroup"]{gap:5px}
[data-testid="stSidebar"] [role="radiogroup"] label{padding:10px 12px;border-radius:7px;
width:100%;margin:0;font-size:.9rem}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked){
background:#1b3442;border:1px solid #315466}
[data-testid="stSidebar"] [role="radiogroup"] label:hover{background:#172638}
h1{font-size:2rem!important;letter-spacing:-.035em;font-weight:650!important;padding-top:0!important}
h2{font-size:1.35rem!important;letter-spacing:-.02em}
h3{font-size:1.05rem!important;font-weight:600!important}
[data-testid="stMetric"]{padding:12px 14px;background:#111e2e;border:1px solid #29374b;
border-radius:8px}
[data-testid="stMetricValue"]{font-variant-numeric:tabular-nums;
font-size:clamp(1rem,1.45vw,1.5rem)}
[data-testid="stMetricLabel"]{color:#aab9ce;font-size:.78rem}
[data-testid="stCaptionContainer"]{color:#aab9ce}
[data-testid="stTabs"] [role="tablist"]{gap:1.3rem;border-bottom:1px solid #29374b}
[data-testid="stTabs"] [role="tab"]{font-size:.85rem}
[data-testid="stVerticalBlockBorderWrapper"]{border-color:#29374b!important}
.helios-brand{display:flex;align-items:center;gap:10px;padding:4px 0 12px;
color:#ecf4ff;font-size:1.4rem;font-weight:750;letter-spacing:.09em}
.helios-brand span{color:#57dbc0;font-size:.75rem;letter-spacing:.04em;
border:1px solid #315466;padding:4px 6px;border-radius:5px}
.workspace-topline{display:flex;justify-content:space-between;align-items:center;
padding-bottom:15px;border-bottom:1px solid #29374b;margin-bottom:24px;gap:12px;
font-size:.78rem;color:#aab9ce}
.workspace-topline strong{color:#e7edf7;font-weight:500}
.mode-label{color:#8ce2cf;background:#142e32;padding:5px 9px;border-radius:5px;
font-size:.68rem;letter-spacing:.06em;white-space:nowrap}
.workspace-step{color:#8da3bc;font-size:.7rem;letter-spacing:.1em;font-weight:650;
margin:3px 0 12px;text-transform:uppercase}
.workspace-note{padding:12px 14px;background:#152132;border-left:2px solid #57dbc0;
border-radius:4px;color:#b9c9dd;font-size:.81rem;line-height:1.5}
[data-testid="stAppDeployButton"]{display:none}
@media(max-width:850px){.stMainBlockContainer{padding:1rem 1rem 2rem}
.workspace-topline{margin-bottom:18px}h1{font-size:1.6rem!important}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}
</style>"""


def _navigate() -> None:
    page = st.session_state.workspace_page
    st.query_params["page"] = PAGES[page][0]
    if page != "Alpha registry" and "run" in st.query_params:
        del st.query_params["run"]


def render_shell() -> str:
    st.html(STYLE)
    route = (str(st.query_params.get("page", "simulation")), str(st.query_params.get("run", "")))
    default = next((name for name, value in PAGES.items() if value[0] == route[0]), "Simulation")
    if route[1]:
        default = "Alpha registry"
    if st.session_state.get("workspace_route") != route:
        st.session_state.workspace_page = default
        st.session_state.workspace_route = route
    st.sidebar.html('<div class="helios-brand">HELIOS <span>LAB</span></div>')
    st.sidebar.caption("Your quantitative research workspace")
    st.sidebar.divider()
    page: str = st.sidebar.radio(
        "Workspace navigation",
        list(PAGES),
        key="workspace_page",
        format_func=lambda x: PAGES[x][1],
        label_visibility="collapsed",
        on_change=_navigate,
    )
    st.sidebar.divider()
    with st.sidebar.expander("Quick guide"):
        st.markdown(
            "**1. Explore** datasets and field definitions.\n\n"
            "**2. Simulate** a template on generated prices.\n\n"
            "**3. Backtest NSE** strategies on retained prices, or review saved research.\n\n"
            "**4. Monitor** simulated PAPER sessions."
        )
        st.caption("Sharpe compares return with variability. Fitness also accounts for turnover.")
    st.sidebar.caption("Local workspace · simulated execution")
    st.html(
        '<div class="workspace-topline"><div>WORKSPACE &nbsp; / &nbsp; '
        f"<strong>{PAGES[page][1]}</strong></div>"
        '<span class="mode-label">SIMULATION ONLY</span></div>'
    )
    return page


def render_datasets() -> None:
    """Display declared contracts without claiming uncollected fields are usable."""
    import pandas as pd

    from helios.equities.field_catalog import nse_catalog

    st.title("Datasets & fields")
    st.write("Find the input, understand its meaning, then build your hypothesis.")
    st.caption(
        "This is HELIOS's declared field catalogue. A field definition does not guarantee "
        "collected history or execution certification."
    )
    catalog = nse_catalog()
    labels = {
        "price_volume": "Prices & volume",
        "fundamental": "Company filings",
        "delivery": "Delivery",
    }
    states = {
        "available_unverified": "History retained · uncertified",
        "collection_required": "Declared fields · see research rounds for collected coverage",
        "sample_only": "Schema sample only",
    }
    dataset = st.selectbox("Dataset", catalog.datasets, format_func=lambda x: labels[x.family])
    a, b, c = st.columns(3)
    a.metric("Market", dataset.market)
    b.metric("Frequency", "Daily" if dataset.frequency == "daily" else "Filing events")
    fields = [field for field in catalog.fields if field.dataset_id == dataset.dataset_id]
    c.metric("Declared fields", len(fields))
    st.info(states[dataset.history_status])
    query = st.text_input("Search fields", placeholder="Try volume, profit or publication…")
    shown = [f for f in fields if query.casefold() in (f.field_id + " " + f.description).casefold()]
    if not shown:
        st.info("No fields match. Try a different search.")
        return
    st.dataframe(
        pd.DataFrame(
            [
                dict(
                    Field=f.field_id,
                    Meaning=f.description,
                    Shape=f.kind,
                    Unit=f.unit,
                    Availability=f.availability,
                )
                for f in shown
            ]
        ),
        hide_index=True,
        width="stretch",
    )
    with st.expander("Source & field details"):
        st.caption(f"Provider: {dataset.provider} · Contract: {dataset.dataset_id}")
        st.link_button("View source", dataset.source_url)
        st.json([f.model_dump(mode="json") for f in shown], expanded=False)
    st.link_button(
        "Explore retained NSE research", "?page=equities", icon=":material/arrow_forward:"
    )
