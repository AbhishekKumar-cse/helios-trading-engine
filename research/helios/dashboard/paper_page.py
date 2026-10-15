"""PAPER page rendering is invoked explicitly, never at worker import time."""

from datetime import UTC, datetime

import pandas as pd
import streamlit as st

from helios.dashboard.control import kill_paper
from helios.dashboard.paper import read_paper


def render_paper() -> None:
    st.title("Paper trading")
    st.caption("PAPER · is_simulated = true · local checkpoints · refresh every 2 seconds")
    st.info(
        "Integration sessions may use a rejected candidate. This page does not imply promotion."
    )

    @st.fragment(run_every=2)
    def checkpoint() -> None:
        try:
            overview = read_paper()
            if not overview["runs"]:
                st.info("No simulated PAPER sessions recorded.")
                return
            run_id = st.selectbox("PAPER session", [r["paper_run_id"] for r in overview["runs"]])
            view = overview if overview["run"]["paper_run_id"] == run_id else read_paper(run_id)
        except Exception:
            st.error("PAPER checkpoints unavailable. Check the local database connection.")
            return
        run, pnl = view["run"], view["pnl"]
        st.write(
            f"Session: {run['status'].upper()} · Risk: {'HALTED' if view['halted'] else 'ARMED'}"
        )
        st.caption(
            f"Read at {datetime.now(UTC).isoformat()}; historical sessions remain historical."
        )
        st.json(run["config_json"]["risk"], expanded=False)
        if run["status"] == "running":
            with st.form(f"kill:{run_id}"):
                actor = st.text_input("Local operator", max_chars=80)
                reason = st.text_input("Halt justification", max_chars=500)
                pressed = st.form_submit_button("Halt this PAPER session", type="primary")
            if pressed:
                try:
                    kill_paper(run_id, actor, reason)
                except ValueError as exc:
                    st.error(str(exc))
                except Exception:
                    st.error("Halt could not be confirmed. Check the local risk journal.")
                else:
                    st.success("PAPER halt committed and audited. New orders are blocked.")
                    st.caption("Pending intents are cancelled when the runner next processes data.")
        if pnl is None:
            st.warning("No P&L checkpoint yet. Performance and positions are unavailable.")
        else:
            timestamp = datetime.fromtimestamp(pnl["ts"] / 1_000_000, UTC)
            age = max(0.0, (datetime.now(UTC) - timestamp).total_seconds())
            st.caption(f"Latest checkpoint: {timestamp.isoformat()} · age {age:.1f} seconds")
            if run["status"] == "running" and age > 10:
                st.warning(
                    "Checkpoint is stale. A running database status is not a feed heartbeat."
                )
            columns = st.columns(4)
            for column, (label, key) in zip(
                columns,
                [
                    ("Net P&L (USDT)", "total"),
                    ("Realised", "realised"),
                    ("Unrealised", "unrealised"),
                    ("Fees", "fees"),
                ],
                strict=True,
            ):
                column.metric(label, str(pnl[key]))
        st.subheader("Latest positions")
        st.dataframe(pd.DataFrame(view["positions"]), hide_index=True, width="stretch")
        st.subheader("Open simulated orders")
        st.dataframe(pd.DataFrame(view["orders"]), hide_index=True, width="stretch")
        if not view["orders"]:
            st.caption("No persisted working orders for this session.")

    checkpoint()
