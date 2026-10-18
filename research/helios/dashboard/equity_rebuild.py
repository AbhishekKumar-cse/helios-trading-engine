"""Read-only view of the repaired, conditional historical minute cohort."""

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from helios.common.lineage import PROJECT_ROOT
from helios.dashboard.equity_research import render_equity_research
from helios.data.equities import sha256
from helios.equities.rebuild import verified_file


def render_rebuilt(snapshot: Path) -> None:
    manifest = json.loads((snapshot / "manifest.json").read_text())
    if manifest["version"] != "nse_public_minutes_v2" or not manifest["complete"]:
        raise ValueError("repaired snapshot is incomplete")
    for name, key in (
        ("sessions.json", "sessions_sha256"),
        ("universe.json", "universe_sha256"),
        ("session_checks.json", "checks_sha256"),
        ("protocol.json", "protocol_sha256"),
    ):
        verified_file(snapshot, name, manifest[key])
    st.subheader("Historical membership · rebuilt minute data")
    st.warning(
        "Conditional research cohort. Unresolved share units are quarantined. "
        "Daily scale checks do not certify minute prices or volumes. No promoted alpha."
    )
    a, b, c = st.columns(3)
    a.metric("Historical companies with bars", len(manifest["files"]))
    b.metric("Retained actual minute bars", f"{manifest['rows']:,}")
    c.metric("Screened research bars", f"{manifest['eligible_rows']:,}")
    st.caption("January 2025–June 2026 · TRAIN / VALID only · Original experiments retained")
    records = {r["symbol"]: r for r in manifest["files"]}
    symbols = sorted(records)
    symbol = st.selectbox("Historical company", symbols, index=symbols.index("RELIANCE"))
    record = records[symbol]
    source = verified_file(snapshot, record["path"], record["sha256"])
    bars = pd.read_parquet(source, filters=[("session_date", "<=", "2026-06-30")])
    st.line_chart(bars.set_index("timestamp")[["source_close"]].tail(800), color="#64d6bb")
    st.caption("Provider-observed prices in their original units; no guessed adjustment factors.")
    checks = pd.read_json(snapshot / "session_checks.json")
    selected = checks.loc[checks.symbol == symbol]
    st.dataframe(selected.groupby("status").size().rename("Sessions"), width="stretch")
    with st.expander("Membership, calendar and exclusions"):
        sessions = json.loads((snapshot / "sessions.json").read_text())
        st.dataframe(
            pd.DataFrame([dict(day=d, **r) for d, r in sessions.items() if r["kind"] != "normal"]),
            hide_index=True,
        )
        st.dataframe(selected, hide_index=True, width="stretch")
        st.caption("Dummy constituents are recorded before listing; no dummy prices are traded.")
    render_equity_research(symbol)
    st.caption(f"Snapshot {snapshot.name} · manifest SHA-256 {sha256(snapshot / 'manifest.json')}")
    st.caption(f"Source: {snapshot.relative_to(PROJECT_ROOT)}")
