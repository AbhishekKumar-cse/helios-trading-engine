"""Scoped retained-data explorer with explicit executable field bindings."""

import json
from dataclasses import asdict

import pandas as pd
import streamlit as st

from helios.common.lineage import PROJECT_ROOT
from helios.dashboard.dataset_inventory import collect_inventory
from helios.dashboard.lab_templates import FIELDS
from helios.dashboard.nse_backtest import datasets
from helios.dashboard.workstation_shell import navigate
from helios.equities.field_catalog import nse_catalog


def render_datasets() -> None:
    st.title("Data Explorer")
    st.caption(
        "Browse retained collections and their actual schemas. Select a "
        "compatible field to start a template."
    )
    refresh = st.button("Refresh inventory", icon=":material/refresh:")
    if refresh or "dataset_inventory_v1" not in st.session_state:
        with st.spinner("Reading retained metadata…"):
            st.session_state.dataset_inventory_v1 = collect_inventory(PROJECT_ROOT)
    inventory, issues = st.session_state.dataset_inventory_v1
    for issue in issues:
        st.warning(issue)
    with st.container(border=True):
        a, b, c = st.columns(3)
        market = a.selectbox("Market", ["All", *sorted({item.market for item in inventory})])
        family = b.selectbox("Data family", ["All", *sorted({item.family for item in inventory})])
        frequency = c.selectbox(
            "Frequency", ["All", *sorted({item.frequency for item in inventory})]
        )
        shown = [
            d
            for d in inventory
            if (market == "All" or d.market == market)
            and (family == "All" or d.family == family)
            and (frequency == "All" or d.frequency == frequency)
        ]
        a, b, c, d = st.columns(4)
        a.metric("Collections", len(shown))
        b.metric("Distinct fields", len({f["Field"] for item in shown for f in item.fields}))
        c.metric("Markets", len({item.market for item in shown}))
        d.metric("Data families", len({item.family for item in shown}))
    if not shown:
        st.info("No retained collections match these filters.")
        return
    dataset = st.selectbox("Collection", shown, format_func=lambda item: item.name)
    fields_tab, coverage, source = st.tabs(["Fields", "Coverage & files", "Source & contracts"])
    with fields_tab:
        a, b = st.columns([3, 1])
        query = a.text_input("Search fields", placeholder="Field name or meaning…")
        category = b.selectbox(
            "Field category", ["All", *sorted({f["Category"] for f in dataset.fields})]
        )
        fields = [
            f
            for f in dataset.fields
            if (category == "All" or f["Category"] == category)
            and query.casefold() in " ".join(f.values()).casefold()
        ]
        if fields:
            st.dataframe(
                pd.DataFrame(fields),
                hide_index=True,
                width="stretch",
                height=330,
                column_config={
                    "Field": st.column_config.TextColumn(width="small"),
                    "Meaning": st.column_config.TextColumn(width="large"),
                    "Availability": st.column_config.TextColumn(width="large"),
                },
            )
            st.download_button(
                "Download fields CSV",
                pd.DataFrame(fields).to_csv(index=False),
                "helios_fields.csv",
                "text/csv",
            )
        else:
            st.info(
                "No fields match."
                if dataset.fields
                else "Raw files retained; no validated queryable schema yet."
            )
        executable = None
        if dataset.market == "NSE" and dataset.frequency in {"1m", "1h"}:
            try:
                executable = next(
                    (
                        choice
                        for choice in datasets(PROJECT_ROOT)
                        if choice.interval == dataset.frequency
                        and (choice.path / "manifest.json").relative_to(PROJECT_ROOT).as_posix()
                        == dataset.evidence
                    ),
                    None,
                )
            except (OSError, ValueError, KeyError):
                executable = None
        if executable is not None:
            a, b = st.columns([2, 1])
            available = [name for name in FIELDS if name in {f["Field"] for f in dataset.fields}]
            field = a.selectbox("Bind observed field", available)
            if b.button("Use in Template Lab", type="primary", width="stretch"):
                st.session_state.lab_dataset_path = str(executable.path)
                st.session_state.lab_dataset = executable
                st.session_state.lab_field = field
                st.session_state.lab_bound_field = field
                navigate("Template Lab")
                st.rerun()
        else:
            st.caption(
                "Catalogue view · executable templates currently use screened NSE "
                "minute/hourly OHLCV collections. Other histories remain available "
                "here with their source restrictions."
            )
        st.caption(dataset.status)
    with coverage:
        a, b, c = st.columns(3)
        a.metric("Retained rows", f"{dataset.rows:,}" if dataset.rows is not None else "Not parsed")
        b.metric("Enumerated symbols", len(dataset.symbols) if dataset.symbols else "Not declared")
        c.metric("Schema fields", len(dataset.fields))
        st.write("**Retained period:**", dataset.period)
        st.caption(
            "Storage coverage includes held-out and quarantined rows. It does not "
            "grant access beyond a frozen research protocol; TEST observation "
            "values remain sealed."
        )
        st.write(
            "**Symbols:**", ", ".join(dataset.symbols) or "Not enumerated in retained metadata"
        )
        if dataset.files:
            st.dataframe(pd.DataFrame(dataset.files), hide_index=True, width="stretch")
        table = pd.DataFrame(
            [
                dict(
                    Dataset=d.name,
                    Market=d.market,
                    Family=d.family,
                    Frequency=d.frequency,
                    Rows=d.rows,
                    Fields=len(d.fields),
                    Period=d.period,
                    Status=d.status,
                )
                for d in shown
            ]
        )
        st.download_button(
            "Download collection inventory CSV",
            table.to_csv(index=False),
            "helios_datasets.csv",
            "text/csv",
        )
    with source:
        st.write(dataset.provider)
        st.write(dataset.access)
        st.code(dataset.evidence, language=None)
        st.caption(
            "Metadata evidence SHA-256: "
            + (dataset.evidence_sha256 or "Raw paths only; no parsed schema claimed")
        )
        st.caption(
            "This view reads Parquet footers and manifests. Bulk input hashes are "
            "recorded references, not a new certification of prices or execution "
            "units."
        )
        st.download_button(
            "Download full dataset metadata JSON",
            json.dumps(asdict(dataset), indent=2),
            "dataset_metadata.json",
            "application/json",
        )
        with st.expander("Declared field contracts & collection gaps"):
            catalog = nse_catalog()
            st.caption(
                "A declared contract is separate from collected history and executable "
                "field bindings."
            )
            st.dataframe(
                pd.DataFrame(
                    [
                        dict(
                            Dataset=f.dataset_id,
                            Field=f.field_id,
                            Meaning=f.description,
                            Shape=f.kind,
                            Unit=f.unit,
                            Availability=f.availability,
                        )
                        for f in catalog.fields
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
