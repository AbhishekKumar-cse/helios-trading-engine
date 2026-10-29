"""Compact research workstation navigation, shared by every existing HELIOS view."""

import streamlit as st

PAGES = {
    "Dashboard": ("dashboard", "Dashboard", "dashboard", "WORKSPACE"),
    "Tasks": ("tasks", "Tasks & matrix", "view_module", "WORKSPACE"),
    "Datasets": ("datasets", "Data Explorer", "database", "RESEARCH"),
    "Template Lab": ("lab", "Template Lab", "science", "RESEARCH"),
    "Nifty 50 equities": ("equities", "NSE backtest", "candlestick_chart", "RESEARCH"),
    "Simulation": ("simulation", "Crypto sandbox", "experiment", "RESEARCH"),
    "Alpha tracker": ("tracker", "Alphas", "layers", "RESULTS"),
    "Alpha registry": ("registry", "Registered results", "fact_check", "RESULTS"),
    "Portfolio": ("portfolio", "Portfolio", "donut_large", "RESULTS"),
    "Paper trading": ("paper", "Paper monitor", "monitor_heart", "OPERATIONS"),
}

STYLE = """<style>
:root{--canvas:#010102;--surface:#0f1011;--raised:#141516;--hairline:#23252a;
--ink:#f7f8f8;--muted:#a6abb5;--accent:#828fff}
.stApp{background:var(--canvas);color:var(--ink)}
.stMainBlockContainer{max-width:1540px;padding:1.15rem 1.25rem 3rem}
[data-testid="stHeader"]{background:transparent!important;height:0!important;min-height:0!important;
pointer-events:none}
[data-testid="stToolbar"]{pointer-events:auto;background:transparent!important;
position:fixed!important;right:6px!important;top:2px!important;
width:fit-content!important;left:auto!important;height:32px!important;min-height:32px!important}
[data-testid="stAppDeployButton"]{display:none}
[data-testid="stStatusWidget"]{display:none}
[data-testid="stSidebar"]{background:var(--surface);border-right:1px solid var(--hairline)}
[data-testid="stSidebar"][data-collapsed="false"]{width:246px!important;
min-width:246px!important;max-width:246px!important}
[data-testid="stSidebar"] .stSidebarBlockContainer{padding:1rem .7rem}
[data-testid="stSidebarHeader"]{height:38px!important;min-height:38px!important;
padding:4px 10px!important}
[data-testid="stSidebarUserContent"]{padding:0 0 20px!important}
[data-testid="stSidebar"] [data-testid="stVerticalBlock"]{gap:.3rem}
[data-testid="stSidebar"] [data-testid="stButton"] button{justify-content:flex-start;
border:1px solid transparent;background:transparent;box-shadow:none;padding:.42rem .65rem;
min-height:32px;border-radius:5px;color:#d0d6e0;font-size:13px;padding:.28rem .65rem}
[data-testid="stSidebar"] [data-testid="stButton"] button>div{
justify-content:flex-start!important}
[data-testid="stSidebar"] [data-testid="stButton"] button[kind="primary"]{
background:#1c1c23;border-color:#34343a;color:#f7f8f8}
[data-testid="stSidebar"] [data-testid="stButton"] button:hover{background:#202024}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"]{font-size:10px;
letter-spacing:.07em;margin:7px 8px 1px;color:#a6abb5}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p{margin-bottom:0}
[data-testid="stSidebar"] [data-testid="stButton"] p{font-size:12px}
h1{font-size:22px!important;font-weight:600!important;letter-spacing:-.5px;
padding-top:0!important;padding-bottom:.35rem!important}
h2{font-size:16px!important;font-weight:600!important;letter-spacing:-.2px}
h3{font-size:14px!important;font-weight:550!important}
p,li{font-size:13px;line-height:1.5}
[data-testid="stCaptionContainer"]{color:#a6abb5;font-size:12px}
[data-testid="stWidgetLabel"] p{font-size:12px;color:#d0d6e0}
[data-testid="stMetric"]{background:var(--surface);border:1px solid var(--hairline);
border-radius:6px;padding:12px 15px}
[data-testid="stMetricValue"]{font-size:23px;font-family:ui-monospace,SFMono-Regular,
Consolas,monospace;font-variant-numeric:tabular-nums;letter-spacing:-.6px}
[data-testid="stMetricLabel"]{font-size:11px;color:#a6abb5;text-transform:uppercase}
[data-testid="stVerticalBlockBorderWrapper"]{border-color:var(--hairline)!important;
border-radius:6px!important;background:var(--surface)}
[data-testid="stExpander"]{border-color:var(--hairline);border-radius:5px}
[data-testid="stTabs"] [role="tablist"]{gap:24px;border-bottom:1px solid var(--hairline)}
[data-testid="stTabs"] [role="tab"]{font-size:12px;padding:8px 0}
.stButton button,.stDownloadButton button,.stLinkButton a{border-radius:5px;font-size:12px}
.stDataFrame{border:1px solid var(--hairline);border-radius:5px}
.helios-brand{font-size:19px;font-weight:650;letter-spacing:.09em;padding:0 9px 12px}
.helios-brand span{color:#828fff;font-size:10px;letter-spacing:.08em;margin-left:7px}
.workspace-topline{display:flex;justify-content:space-between;align-items:center;
gap:12px;border-bottom:1px solid var(--hairline);padding:0 42px 12px 0;margin-bottom:8px;
color:#a6abb5;font-size:11px;letter-spacing:.03em}
.workspace-topline strong{color:#f7f8f8;font-weight:500}
.mode-label{font-family:ui-monospace,monospace;color:#aeb7ff;border:1px solid #34343a;
padding:4px 7px;border-radius:4px;font-size:10px;white-space:nowrap}
.workspace-step{font-size:11px;color:#a6abb5;letter-spacing:.08em;text-transform:uppercase;
margin:1px 0 12px}.workspace-note{border-left:2px solid #828fff;padding:10px 14px;
background:#141516;color:#d0d6e0;font-size:12px}
code,pre{font-variant-numeric:tabular-nums}
@media(max-width:850px){.stMainBlockContainer{padding:1rem .9rem 2rem}
.workspace-topline{margin-bottom:16px}h1{font-size:21px!important}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}
</style>"""


def navigate(page: str) -> None:
    if page not in PAGES:
        raise ValueError("unknown workstation page")
    st.query_params["page"] = PAGES[page][0]
    st.session_state.workspace_page = page
    if page != "Alpha registry" and "run" in st.query_params:
        del st.query_params["run"]


def render_shell() -> str:
    route = str(st.query_params.get("page", "dashboard"))
    page = next((name for name, value in PAGES.items() if value[0] == route), "Dashboard")
    if st.query_params.get("run"):
        page = "Alpha registry"
    st.session_state.workspace_page = page
    st.html(STYLE)
    st.sidebar.html('<div class="helios-brand">HELIOS<span>RESEARCH</span></div>')
    group = ""
    for name, (_, label, icon, section) in PAGES.items():
        if section != group:
            st.sidebar.caption(section)
            group = section
        st.sidebar.button(
            label,
            key="nav_" + name,
            icon=f":material/{icon}:",
            type="primary" if page == name else "secondary",
            width="stretch",
            on_click=navigate,
            args=(name,),
        )
    st.sidebar.divider()
    st.sidebar.caption("Local workspace · simulated execution")
    with st.sidebar.expander("Research guide"):
        st.write(
            "Explore retained fields, define a template, review its scope, then "
            "queue a bounded development experiment. Inspect costs and evidence "
            "before drawing conclusions."
        )
    st.html(
        '<div class="workspace-topline"><span>WORKSPACE &nbsp; / &nbsp; '
        f"<strong>{PAGES[page][1]}</strong></span>"
        '<span class="mode-label">LOCAL · SIMULATION</span></div>'
    )
    return page
