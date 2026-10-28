"""Browse retained collections, their observed schemas and research restrictions."""

import json
from dataclasses import asdict

import pandas as pd
import streamlit as st

from helios.common.lineage import PROJECT_ROOT
from helios.dashboard.dataset_inventory import collect_inventory
from helios.equities.field_catalog import nse_catalog


def render_datasets() -> None:
    st.title("Datasets & fields")
    st.write("Browse the data already retained in HELIOS, then inspect its fields and coverage.")
    st.caption(
        "File rows and schemas come from Parquet footers and retained manifests. "
        "Coverage is storage coverage, not permission to access sealed TEST observations. "
        "Raw archives and schema samples are labelled separately."
    )
    refresh = st.button("Refresh data inventory", icon=":material/refresh:")
    if refresh or "dataset_inventory_v1" not in st.session_state:
        with st.spinner("Reading retained metadata…"):
            st.session_state.dataset_inventory_v1 = collect_inventory(PROJECT_ROOT)
    datasets, issues = st.session_state.dataset_inventory_v1
    for issue in issues:
        st.warning(issue)
    a, b, c, d = st.columns(4)
    a.metric("Retained collections", len(datasets))
    b.metric("Schema fields", len({f["Field"] for item in datasets for f in item.fields}))
    c.metric("Markets", len({item.market for item in datasets}))
    d.metric("Families", len({item.family for item in datasets}))
    left, middle, right = st.columns(3)
    market = left.selectbox("Market", ["All", *sorted({item.market for item in datasets})])
    family = middle.selectbox("Data family", ["All", *sorted({item.family for item in datasets})])
    frequency = right.selectbox(
        "Frequency", ["All", *sorted({item.frequency for item in datasets})]
    )
    shown = [
        item
        for item in datasets
        if (market == "All" or item.market == market)
        and (family == "All" or item.family == family)
        and (frequency == "All" or item.frequency == frequency)
    ]
    if shown:
        table = pd.DataFrame(
            [
                dict(
                    Dataset=item.name,
                    Market=item.market,
                    Family=item.family,
                    Frequency=item.frequency,
                    Symbols=len(item.symbols) or None,
                    Rows=item.rows,
                    Fields=len(item.fields),
                    Period=item.period,
                    Status=item.status,
                )
                for item in shown
            ]
        )
        st.dataframe(table, hide_index=True, width="stretch", height=300)
        st.download_button(
            "Download dataset inventory CSV",
            table.to_csv(index=False).encode(),
            "helios_datasets.csv",
            "text/csv",
        )
        dataset = st.selectbox("Inspect dataset", shown, format_func=lambda item: item.name)
        st.subheader(dataset.name)
        st.info(dataset.status)
        st.caption(dataset.provider + " · " + dataset.access)
        st.write("**Retained period:**", dataset.period)
        st.write(
            "**Symbols:**",
            ", ".join(dataset.symbols) or "Not enumerated in retained metadata; no count inferred",
        )
        query = st.text_input(
            "Search fields", placeholder="Try close, volume, profit, volatility or availability…"
        )
        fields = [
            field
            for field in dataset.fields
            if query.casefold() in " ".join(field.values()).casefold()
        ]
        if fields:
            st.dataframe(pd.DataFrame(fields), hide_index=True, width="stretch")
            st.download_button(
                "Download fields CSV",
                pd.DataFrame(fields).to_csv(index=False).encode(),
                "helios_fields.csv",
                "text/csv",
            )
        else:
            st.info(
                "No fields match."
                if dataset.fields
                else "Raw files retained; no validated queryable schema yet."
            )
        with st.expander("Files, lineage & coverage details"):
            st.code(dataset.evidence, language=None)
            st.caption(
                "Metadata evidence SHA-256: "
                + (dataset.evidence_sha256 or "Raw-file paths only; no validation claimed")
            )
            st.caption(
                "Footer counts include all retained rows, including quarantined/ineligible "
                "observations. Manifest hashes below are recorded references; "
                "this view does not rehash bulk price files."
            )
            if dataset.files:
                st.dataframe(pd.DataFrame(dataset.files), hide_index=True, width="stretch")
        st.download_button(
            "Download full dataset metadata JSON",
            json.dumps(asdict(dataset), indent=2),
            "dataset_metadata.json",
            "application/json",
        )
    else:
        st.info("No retained collections match these filters.")
    with st.expander("Declared field contracts & collection gaps"):
        catalog = nse_catalog()
        st.caption(
            "Contracts describe intended semantics. The collected inventory above determines "
            "what files actually exist; declaration alone is not availability or certification."
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
    st.link_button("View alpha × dataset tracker", "?page=tracker")
