"""Comparable sandbox accounts and overlap-qualified correlation, without promotion."""

from __future__ import annotations

from typing import Any

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from helios.dashboard.tasks_page import render_account
from helios.dashboard.workstation_data import retained_accounts


def compare(accounts: list[dict[str, Any]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not accounts:
        raise ValueError("select retained accounts")
    first = accounts[0]["protocol"]
    identity = (
        first["manifest_sha256"],
        first["interval"],
        first["options"]["start"],
        first["options"]["end"],
        first["options"]["capital"],
    )
    calendar = [row["day"] for row in accounts[0]["result"]["scenarios"]["1"]["daily"]]
    series = {}
    curves = {"Day": calendar}
    for index, account in enumerate(accounts):
        p = account["protocol"]
        other = (
            p["manifest_sha256"],
            p["interval"],
            p["options"]["start"],
            p["options"]["end"],
            p["options"]["capital"],
        )
        if other != identity or not p.get("cash_carries_between_flat_sessions"):
            raise ValueError(
                "Compare the same manifest, frequency, date range, capital and "
                "carried-cash convention"
            )
        base = account["result"]["scenarios"]["1"]["daily"]
        if [row["day"] for row in base] != calendar:
            raise ValueError(
                "Observed session calendars differ; missing days are not filled with zero"
            )
        label = f"{p['options']['symbol']} · {index + 1}"
        series[label] = [row["net_return"] for row in base]
        curves[label] = [float(row["end_cash"]) for row in base]
    frame = pd.DataFrame(curves).set_index("Day")
    # No daily rebalancing, missing-return fill or pooled-fill assumption.
    frame["Mean account equity"] = frame.mean(axis=1)
    returns = pd.DataFrame(series)
    correlation = returns.corr(min_periods=20) if len(calendar) >= 20 else pd.DataFrame()
    return frame, correlation


def render_portfolio() -> None:
    st.title("Portfolio")
    st.caption("Compare retained development accounts, cost scenarios and daily-return overlap.")
    accounts, issues = retained_accounts()
    for issue in issues:
        st.warning(issue)
    if not accounts:
        st.info(
            "No complete development accounts yet. Run a retained-data backtest or "
            "a reviewed Template Lab experiment."
        )
        return
    selected = st.multiselect(
        "Development accounts",
        list(range(len(accounts))),
        default=[0],
        format_func=lambda i: (
            f"{accounts[i]['protocol']['options']['symbol']} · "
            f"{accounts[i]['protocol']['interval']} · "
            f"{accounts[i]['protocol']['options']['start']} · "
            f"{accounts[i]['protocol']['run_id'][-8:]}"
        ),
    )
    if not selected:
        st.info("Select an account to inspect.")
        return
    chosen = [accounts[i] for i in selected]
    table = []
    for account in chosen:
        p, r = account["protocol"], account["result"]
        base = r["scenarios"]["1"]["summary"]
        stress = r["scenarios"].get("2", {}).get("summary", {})
        table.append(
            dict(
                Company=p["options"]["symbol"],
                Expression=p["options"].get("expression") or p["options"]["strategy"],
                Normal=base["net_return"] * 100,
                Doubled=None if not stress else stress["net_return"] * 100,
                Sharpe="Undefined" if base["sharpe"] is None else f"{base['sharpe']:.2f}",
                Fills=base["fills"],
                Status="Development · nonpromotable",
            )
        )
    st.dataframe(
        pd.DataFrame(table),
        hide_index=True,
        width="stretch",
        column_config={
            "Normal": st.column_config.NumberColumn("Normal %", format="%.2f"),
            "Doubled": st.column_config.NumberColumn("Doubled costs %", format="%.2f"),
        },
    )
    st.subheader("Account comparison")
    try:
        frame, correlation = compare(chosen)
        chart = (
            alt.Chart(frame.reset_index().melt("Day", var_name="Account", value_name="Equity"))
            .mark_line(point=True)
            .encode(
                x=alt.X("Day:O", axis=alt.Axis(labelAngle=0)),
                y=alt.Y("Equity:Q", title="Equity / INR", scale=alt.Scale(zero=False)),
                color="Account:N",
                tooltip=["Day:O", "Account:N", alt.Tooltip("Equity:Q", format=",.2f")],
            )
            .properties(height=280)
        )
        st.altair_chart(chart, width="stretch")
        st.caption(
            "Mean of accounts with equal initial capital, each using its own "
            "retained fills and fees. This is a diagnostic comparison; aggregate "
            "netting, allocation and combined risk have not been replayed."
        )
        st.subheader("Daily-return correlation")
        if len(chosen) < 2:
            st.info("Select at least two comparable accounts.")
        elif correlation.empty or not np.isfinite(correlation.to_numpy()).any():
            st.info(
                "At least 20 shared completed sessions and nonconstant returns are "
                "required. Correlation is unavailable for this selection."
            )
        else:
            st.dataframe(correlation, width="stretch")
            st.caption(
                "Pearson correlation · identical observed session calendars · "
                "undefined entries stay blank"
            )
    except ValueError as error:
        st.info(str(error))
    st.subheader("Selected account evidence")
    inspected = st.selectbox(
        "Inspect account", chosen, format_func=lambda a: a["protocol"]["run_id"]
    )
    render_account(inspected)
