"""Read-only exploration of downloaded equities and retained development fits."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from helios.common.config import load_config
from helios.common.lineage import PROJECT_ROOT
from helios.data.equities import EquityPilotConfig, constituents, sha256


def retained_snapshots(root: Path) -> list[Path]:
    return sorted(root.glob("*/manifest.json"), reverse=True)


def read_manifest(path: Path) -> dict[str, Any]:
    manifest: dict[str, Any] = json.loads(path.read_text())
    roster = path.parent / "constituents.csv"
    if sha256(roster) != manifest["universe_sha256"]:
        raise ValueError("constituent snapshot hash mismatch")
    constituents(roster.read_bytes())
    return manifest


def read_development_bars(
    snapshot: Path, record: dict[str, Any], config: EquityPilotConfig
) -> pd.DataFrame:
    path = snapshot / record["path"]
    if not path.resolve().is_relative_to(snapshot.resolve()) or sha256(path) != record["sha256"]:
        raise ValueError("equity bar fingerprint mismatch")
    interval = record["interval"]
    if interval == "1d":
        end = config.daily_valid_end
    elif interval == "60m":
        end = config.hourly_valid_end
    elif interval == "1m":
        end = config.end_exclusive
    else:
        raise ValueError("unsupported interval")
    return pd.read_parquet(path, filters=[("session_date", "<=", end.isoformat())])


def render_equities() -> None:
    st.caption("HELIOS · NSE EQUITIES · LOCAL RESEARCH")
    st.title("Nifty 50 research lab")
    st.write("Real downloaded equity bars and retained LightGBM development models.")
    st.info(
        "Current Nifty constituents with Yahoo-distributed prices. Historical membership is "
        "not reconstructed. Model validation is experimental; no trading P&L or promoted alpha."
    )
    snapshots = retained_snapshots(PROJECT_ROOT / "data/equities/nifty50")
    if not snapshots:
        st.info("No completed equity download is available yet.")
        return
    selected = st.selectbox("Data snapshot", snapshots, format_func=lambda path: path.parent.name)
    try:
        manifest = read_manifest(selected)
        config = load_config(selected.parent / "protocol.json", EquityPilotConfig)
    except (OSError, ValueError, KeyError):
        st.error("The selected snapshot could not be verified.")
        return
    columns = st.columns(3)
    for column, interval, title in zip(
        columns, ("1d", "60m", "1m"), ("Daily bars", "Hourly bars", "Minute bars"), strict=True
    ):
        records = [record for record in manifest["files"] if record["interval"] == interval]
        column.metric(title, f"{sum(record['retained_bars'] for record in records):,}")
        column.caption(f"{len(records)} / 50 companies")
    st.caption(
        f"Downloaded {manifest['created_at']} · Currency INR · Exchange timezone Asia/Kolkata"
    )
    left, right = st.columns([2, 1])
    members = {member["Symbol"]: member["Company Name"] for member in manifest["members"]}
    symbol = left.selectbox(
        "Company", sorted(members), format_func=lambda key: f"{key} · {members[key]}"
    )
    interval = right.selectbox(
        "Bar interval",
        ["1d", "60m", "1m"],
        format_func=lambda key: {"1d": "Daily", "60m": "Hourly", "1m": "Minute"}[key],
    )
    record = next(
        (
            entry
            for entry in manifest["files"]
            if entry["symbol"] == symbol and entry["interval"] == interval
        ),
        None,
    )
    if record is None:
        st.warning("This company's requested interval was unavailable; see download failures.")
    else:
        try:
            bars = read_development_bars(selected.parent, record, config)
        except (OSError, ValueError, KeyError):
            st.error("Bar data failed integrity verification.")
        else:
            st.subheader(f"{symbol} · {'adjusted close' if interval == '1d' else 'close'} · INR")
            price = "adjusted_close" if interval == "1d" else "close"
            st.line_chart(bars.set_index("timestamp")[[price]].tail(800), color="#64d6bb")
            st.caption(
                "Daily/hourly charts stop at VALID; reserved TEST prices are not displayed. "
                "Minute bars show recent ingestion coverage only. Missing bars are not filled."
            )
            if interval == "1m":
                per_session = bars.groupby("session_date").size().rename("Observed minute bars")
                st.dataframe(per_session, width="stretch")
                st.caption("Normal sessions have 375 one-minute slots. This free source has gaps.")
    reports = sorted((PROJECT_ROOT / "reports_out/equities").glob("*/report.json"), reverse=True)
    matching = []
    for path in reports:
        report = json.loads(path.read_text())
        if report.get("snapshot") == str(selected.parent.relative_to(PROJECT_ROOT)):
            matching.append((path, report))
    st.subheader("Retained model validation")
    if not matching:
        st.info("Training has not completed for this snapshot yet.")
    else:
        path, report = matching[0]
        rows = []
        for key, model in report["models"].items():
            rows.append(
                {
                    "Interval": "Daily" if key == "1d" else "Hourly",
                    "TRAIN samples": model["train_samples"],
                    "VALID samples": model["valid_samples"],
                    "Companies in fit": model["train_symbols"],
                    "Direction accuracy": model["model_metrics"]["accuracy"],
                    "Constant baseline accuracy": model["train_constant_baseline"]["accuracy"],
                    "ROC AUC": model["model_metrics"]["roc_auc"],
                    "Log loss": model["model_metrics"]["log_loss"],
                }
            )
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.caption(
            "Daily predicts the next session's open-to-close direction. Hourly predicts the "
            "next full hour within the same session. VALID selects early stopping. "
            f"Model TEST accesses: {report['test_observation_accesses']}."
        )
        st.download_button("Download model report", path.read_bytes(), "nifty50_model_report.json")
    with st.expander("Company coverage and data quality"):
        st.dataframe(
            pd.DataFrame(
                [
                    dict(
                        Company=entry["symbol"],
                        Interval=entry["interval"],
                        Bars=entry["retained_bars"],
                        First=entry["first_session"],
                        Last=entry["last_session"],
                        Partial=entry["partial_bars"],
                        Rejected=sum(entry["rejected_rows"].values()),
                    )
                    for entry in manifest["files"]
                ]
            ),
            hide_index=True,
            width="stretch",
        )
        st.write("Download failures", manifest["failures"])
