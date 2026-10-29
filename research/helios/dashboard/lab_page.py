"""Field-aware template setup, finite preview and explicit durable job submission."""

import hashlib
import json
from datetime import date
from decimal import Decimal

import pandas as pd
import streamlit as st

from helios.common.lineage import PROJECT_ROOT
from helios.dashboard.lab_store import MAX_JOBS, enqueue, fingerprint
from helios.dashboard.lab_templates import FIELDS, OPERATORS, TEMPLATES, expand
from helios.dashboard.lab_worker import start_worker
from helios.dashboard.nse_backtest import FIRST, LAST, NseOptions, datasets
from helios.dashboard.workstation_shell import navigate


def _retain_expression() -> None:
    st.session_state.lab_expression_draft = st.session_state.lab_expression


def render_lab() -> None:
    st.title("Template Lab")
    st.caption(
        "Bind fields and lookbacks to a hypothesis, review the candidates, "
        "then add a bounded development task."
    )
    try:
        choices = datasets(PROJECT_ROOT)
    except (OSError, ValueError, KeyError):
        st.error("Executable dataset metadata could not be verified.")
        return
    if not choices:
        st.info(
            "No screened minute/hourly dataset is available for execution. Data "
            "Explorer lists retained collections and gaps."
        )
        return
    with st.container(border=True):
        st.subheader("Market")
        a, b, c = st.columns([1, 1, 2])
        a.text_input("Market", value="NSE cash · INR", disabled=True)
        preferred = st.session_state.get("lab_dataset_path", "")
        index = next((i for i, d in enumerate(choices) if str(d.path) == preferred), 0)
        dataset = b.selectbox(
            "Frequency", choices, index=index, format_func=lambda d: d.interval, key="lab_dataset"
        )
        defaults = ["RELIANCE"] if "RELIANCE" in dataset.symbols else list(dataset.symbols[:1])
        symbols = c.multiselect(
            "Companies",
            dataset.symbols,
            default=defaults,
            max_selections=3,
            key="lab_symbols_" + dataset.interval,
        )
        st.caption(
            "Retained screened observations · Jan 9–Jun 30, 2026 · conditional development use"
        )
    with st.container(border=True):
        a, b = st.columns([1, 3])
        preset = a.selectbox("Starting template", list(TEMPLATES), key="lab_preset")
        if st.session_state.get("lab_preset_seen") != preset:
            st.session_state.lab_expression = TEMPLATES[preset]
            st.session_state.lab_expression_draft = TEMPLATES[preset]
            st.session_state.lab_preset_seen = preset
        elif "lab_expression" not in st.session_state:
            st.session_state.lab_expression = st.session_state.get(
                "lab_expression_draft", TEMPLATES[preset]
            )
        b.subheader("Write your template")
        template = st.text_area(
            "Expression",
            key="lab_expression",
            on_change=_retain_expression,
            height=100,
            help=(
                "Use `$field` and `$lookback`. The existing HELIOS DSL validates every "
                "expanded candidate."
            ),
        )
        st.caption(
            "`$field` chooses an observed scalar field. `$lookback` counts completed "
            "bars inside a single session."
        )
        a, b = st.columns(2)
        field = a.selectbox(
            "$field",
            FIELDS,
            index=FIELDS.index(st.session_state.get("lab_field", "close")),
            key="lab_bound_field",
        )
        lookback_text = b.text_input(
            "$lookback · completed bars",
            value="5, 10, 20" if dataset.interval == "1m" else "1, 2, 3",
            key="lab_windows_" + dataset.interval,
        )
        with st.expander("Operators & availability"):
            st.code(", ".join(OPERATORS), language=None)
            st.write(
                "No backfill of prices or volume. Missing/warmup values stay "
                "unavailable. Cross-sectional operators need a universe contract and "
                "are not enabled in this single-instrument session lab."
            )
            st.write(
                "Signals reset every session. Orders use the next observed opening; "
                "targets are clipped to long/flat. These are bar windows, not "
                "10/20/520 trading-day histories."
            )
    with st.container(border=True):
        st.subheader("Experiment settings")
        hypothesis = st.text_input(
            "Hypothesis",
            placeholder="Why should this signal predict a move after costs?",
            max_chars=1000,
            key="lab_hypothesis",
        )
        a, b, c = st.columns(3)
        dates = a.date_input(
            "Development dates",
            value=(date(2026, 1, 12), date(2026, 1, 12)),
            min_value=FIRST,
            max_value=LAST,
            key="lab_dates",
        )
        capital = b.number_input(
            "Starting capital / INR",
            min_value=1000,
            max_value=10000000,
            value=100000,
            step=1000,
            key="lab_capital",
        )
        allocation = c.select_slider(
            "Allocation / %", options=list(range(5, 85, 5)), value=10, key="lab_allocation"
        )
        st.caption(
            "Whole shares · existing fees/tax model · 5 bps slippage per side · "
            "independent normal and doubled-cost accounts · up to 31 calendar days "
            "per candidate"
        )
    options, errors = [], []
    try:
        windows = list(
            dict.fromkeys(int(part.strip()) for part in lookback_text.split(",") if part.strip())
        )
        if not windows or len(windows) * len(symbols) > MAX_JOBS or not symbols:
            raise ValueError(f"Choose companies and lookbacks producing 1–{MAX_JOBS} candidates")
        if len(dates) != 2:
            raise ValueError("Choose a start and end date")
        for symbol in symbols:
            for window in windows:
                expression = expand(template, field, window, dataset.interval)
                options.append(
                    NseOptions(
                        symbol=symbol,
                        start=dates[0],
                        end=dates[1],
                        strategy="Trend following",
                        lookback=window,
                        capital=Decimal(capital),
                        allocation_pct=allocation,
                        compare_costs=True,
                        expression=expression,
                    )
                )
        if len(hypothesis.strip()) < 15:
            errors.append("Write a hypothesis of at least 15 characters before queuing.")
    except (ValueError, TypeError) as error:
        errors.append(str(error))
    st.subheader("Experiment preview")
    a, b, c, d = st.columns(4)
    a.metric("Candidates", len(options))
    b.metric("Cost scenarios", 2)
    c.metric("Window unit", dataset.interval + " bars")
    d.metric("Formal eligibility", "Not assessed")
    if options:
        st.dataframe(
            pd.DataFrame(
                [
                    dict(
                        Company=o.symbol,
                        Lookback=o.lookback,
                        Expression=o.expression,
                        Start=str(o.start),
                        End=str(o.end),
                        Scope="Development · session reset",
                    )
                    for o in options
                ]
            ),
            hide_index=True,
            width="stretch",
        )
        st.caption(
            "The source fingerprint, hypothesis, selected manifest, parameters and "
            "cost scenarios are frozen when you add the task. Every candidate is "
            "retained; no automatic winner selection or gate changes."
        )
    for problem in errors:
        st.info(problem)
    source = fingerprint(PROJECT_ROOT)
    signature = hashlib.sha256(
        json.dumps(
            dict(
                source=source,
                manifest=dataset.manifest_sha256,
                template=template,
                field=field,
                hypothesis=hypothesis,
                options=[o.model_dump(mode="json") for o in options],
            ),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    if st.session_state.get("lab_preview_signature") != signature:
        st.session_state.lab_reviewed = False
        st.session_state.lab_preview_signature = signature
    reviewed = st.checkbox(
        "I reviewed the hypothesis, scope, trial count and both cost scenarios", key="lab_reviewed"
    )
    a, b = st.columns([1, 1])
    action = a.button(
        "Add to Tasks",
        disabled=bool(errors) or not reviewed,
        type="primary",
        width="stretch",
        icon=":material/add_task:",
    )
    run_now = b.button(
        "Run now",
        disabled=bool(errors) or not reviewed,
        width="stretch",
        icon=":material/play_arrow:",
    )
    if action or run_now:
        try:
            batch, ids, reused = enqueue(
                PROJECT_ROOT,
                dataset,
                options,
                hypothesis=hypothesis,
                template=template,
                field=field,
                expected_source=source,
            )
            if run_now:
                start_worker(PROJECT_ROOT)
            st.session_state.lab_notice = (
                f"{len(ids) - reused} new jobs · {reused} existing requests reused · {batch}"
            )
            navigate("Tasks")
            st.rerun()
        except (OSError, ValueError):
            st.error(
                "The frozen experiment could not be queued. Refresh the dataset and "
                "review the preview."
            )
