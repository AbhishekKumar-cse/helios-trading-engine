"""Interactive replay of fresh synthetic executions through the shared backend."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pandas as pd
import streamlit as st

from helios.dashboard.simulation import SCENARIOS, STRATEGIES, DemoOptions, DemoRun, run_demo


def utc(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp / 1_000_000, UTC).isoformat()


def replay_view(run: DemoRun, cursor: int) -> dict[str, Any]:
    artifact, trace = run.artifact, run.artifact.trace
    if not 0 <= cursor <= len(artifact.bars):
        raise ValueError("replay cursor outside simulated observations")
    capital = artifact.config.strategy.capital
    snapshots = trace.snapshots[:cursor]
    clock = snapshots[-1].timestamp if snapshots else artifact.config.start_us - 1
    # A close precedes the next opening at the same timestamp. Do not reveal a
    # fill from that next opening before its bar has entered the replay.
    fills = [r.fill for r in trace.reports if r.fill is not None and r.fill.timestamp < clock]
    candles = [
        dict(
            time=utc(bar.open_time),
            open=float(bar.open),
            high=float(bar.high),
            low=float(bar.low),
            close=float(bar.close),
            direction="Up" if bar.close >= bar.open else "Down",
        )
        for bar in artifact.bars[:cursor]
    ]
    peak, drawdown = capital, Decimal(0)
    equity = [dict(time=utc(artifact.config.start_us), equity=float(capital), pnl=0.0)]
    for snapshot in snapshots:
        peak = max(peak, snapshot.equity)
        drawdown = max(drawdown, (peak - snapshot.equity) / peak)
        equity.append(
            dict(
                time=utc(snapshot.timestamp),
                equity=float(snapshot.equity),
                pnl=float(snapshot.equity - capital),
            )
        )
    fill_table = [
        dict(
            Time=utc(fill.timestamp),
            Side=fill.side.value,
            Quantity=str(fill.quantity),
            Price=str(fill.price),
            Fee=str(fill.fee),
            Order=fill.order_id,
        )
        for fill in fills
    ]
    order_table = []
    for order in trace.orders:
        if order.request.timestamp < clock:
            order_table.append(
                dict(
                    Created=utc(order.request.timestamp),
                    Side=order.request.side.value,
                    Quantity=str(order.request.quantity),
                    State="FILLED"
                    if any(f.order_id == order.order_id for f in fills)
                    else "QUEUED",
                    Order=order.order_id,
                )
            )
    return dict(
        candles=candles,
        equity=equity,
        fills=fill_table,
        orders=order_table,
        markers=[
            dict(time=utc(f.timestamp), price=float(f.price), side=f.side.value) for f in fills
        ],
        pnl=snapshots[-1].equity - capital if snapshots else Decimal(0),
        cash=snapshots[-1].cash if snapshots else capital,
        fees=snapshots[-1].fees if snapshots else Decimal(0),
        position=trace.positions[cursor - 1].quantity if cursor else Decimal(0),
        price=artifact.bars[cursor - 1].close if cursor else artifact.bars[0].open,
        drawdown=drawdown,
        halted=any(event.timestamp <= clock for event in run.trips),
        rejects=[
            dict(Time=utc(d.timestamp), Reason=d.reason.value)
            for d in trace.decisions
            if d.timestamp < clock and not d.accepted
        ],
        unavailable=sum(s.status.value == "UNAVAILABLE" for s in artifact.signals[:cursor]),
    )


def price_chart(view: dict[str, Any], *, price_title: str = "Synthetic price / USDT") -> None:
    st.vega_lite_chart(
        spec={
            "height": 300,
            "layer": [
                {
                    "data": {"values": view["candles"]},
                    "mark": "rule",
                    "encoding": {
                        "x": {"field": "time", "type": "temporal", "title": None},
                        "y": {
                            "field": "low",
                            "type": "quantitative",
                            "scale": {"zero": False},
                            "title": price_title,
                        },
                        "y2": {"field": "high"},
                        "color": {
                            "field": "direction",
                            "scale": {"domain": ["Up", "Down"], "range": ["#39d9b3", "#fa7188"]},
                            "legend": None,
                        },
                    },
                },
                {
                    "data": {"values": view["candles"]},
                    "mark": {"type": "bar", "size": 4},
                    "encoding": {
                        "x": {"field": "time", "type": "temporal"},
                        "y": {"field": "open", "type": "quantitative", "scale": {"zero": False}},
                        "y2": {"field": "close"},
                        "color": {
                            "field": "direction",
                            "scale": {"domain": ["Up", "Down"], "range": ["#39d9b3", "#fa7188"]},
                            "legend": None,
                        },
                        "tooltip": [
                            {"field": "time", "type": "temporal"},
                            *[
                                {"field": k, "type": "quantitative", "format": ",.2f"}
                                for k in ("open", "high", "low", "close")
                            ],
                        ],
                    },
                },
                {
                    "data": {"values": view["markers"]},
                    "mark": {"type": "point", "filled": True, "size": 100, "stroke": "#0b1425"},
                    "encoding": {
                        "x": {"field": "time", "type": "temporal"},
                        "y": {"field": "price", "type": "quantitative", "scale": {"zero": False}},
                        "shape": {
                            "field": "side",
                            "scale": {
                                "domain": ["BUY", "SELL"],
                                "range": ["triangle-up", "triangle-down"],
                            },
                            "legend": None,
                        },
                        "color": {
                            "field": "side",
                            "scale": {"domain": ["BUY", "SELL"], "range": ["#71acff", "#ffbe70"]},
                            "legend": None,
                        },
                        "tooltip": [{"field": "side"}, {"field": "price", "format": ",.2f"}],
                    },
                },
            ],
            "resolve": {"scale": {"color": "independent"}},
            "config": {"background": "transparent", "view": {"stroke": None}},
        },
        width="stretch",
    )


def render_simulation() -> None:
    st.title("Build & simulate")
    st.write("Choose a strategy, test an idea, understand the result.")
    st.caption("SYNTHETIC DEMO · generated BTC prices · simulated execution · 1-hour bars")
    settings, results = st.columns([1, 2.65], gap="large")
    with settings:
        with st.container(border=True):
            st.html('<div class="workspace-step">01 / Configure your idea</div>')
            submitted = st.button(
                "Run simulation", type="primary", width="stretch", icon=":material/play_arrow:"
            )
            strategy = st.selectbox("Strategy", STRATEGIES)
            lookback = st.slider(
                "Signal lookback / bars",
                1,
                24,
                6,
                help="Only completed closes enter the signal. Orders fill at the next opening.",
            )
            formula = (
                "1  # long after warm-up"
                if strategy == "Buy and hold"
                else ("-" if strategy == "Mean reversion" else "")
                + f"sign(close - lag(close, {lookback}))"
            )
            st.caption("Signal preview · template notation")
            st.code(formula, language="python", wrap_lines=True)
            scenario = st.selectbox("Price scenario", SCENARIOS)
            capital = st.number_input(
                "Starting capital / USDT", min_value=100, max_value=1000000, value=10000, step=1000
            )
            bars = st.selectbox(
                "Simulation length",
                [96, 168, 336],
                index=1,
                format_func=lambda n: f"{n // 24} days · {n} bars",
            )
            with st.expander("Costs, position size & risk"):
                allocation = st.slider("Target allocation / %", 5, 80, 25, 5)
                loss = st.slider("Daily loss guard / %", 0.1, 20.0, 5.0, 0.1)
                seed = st.number_input(
                    "Random seed", min_value=0, max_value=2**32 - 1, value=42, step=1
                )
                st.caption("10 bps fee + 2 bps slippage per side. A loss trip blocks new orders.")
            st.caption(
                "Synthetic data means computer-generated prices, not actual market observations. "
                "Use NSE research to backtest retained equity prices."
            )
        st.link_button(
            "Explore NSE research",
            "?page=equities",
            width="stretch",
            icon=":material/arrow_forward:",
        )
    options = DemoOptions(
        strategy=strategy,
        scenario=scenario,
        capital=capital,
        bars=bars,
        allocation_pct=allocation,
        daily_loss_pct=loss,
        lookback=lookback,
        seed=seed,
    )
    if submitted or "sandbox_run" not in st.session_state:
        try:
            with results, st.spinner("Running your simulation…"):
                st.session_state.sandbox_run = run_demo(options)
                st.session_state.sandbox_cursor = (
                    0 if submitted else len(st.session_state.sandbox_run.artifact.bars)
                )
                st.session_state.sandbox_playing = submitted
                st.session_state.sandbox_preview = not submitted
        except Exception:
            with results:
                st.error("The simulation could not finish. Your previous runs are kept.")
            return
    with results:
        if options != st.session_state.sandbox_run.options:
            st.info("Settings changed. Select Run simulation to update these results.")

        @st.fragment(run_every=0.5 if st.session_state.sandbox_playing else None)
        def playback() -> None:
            run = st.session_state.sandbox_run
            total = len(run.artifact.bars)
            playing = st.session_state.sandbox_playing
            # Advance only on a replay tick, never by exposing future fills.
            if playing:
                st.session_state.sandbox_cursor = min(
                    total,
                    st.session_state.sandbox_cursor + st.session_state.get("sandbox_speed", 4),
                )
                if st.session_state.sandbox_cursor == total:
                    st.session_state.sandbox_playing = False
                    st.rerun()
            cursor = st.session_state.sandbox_cursor
            view = replay_view(run, cursor)
            state = (
                "EXAMPLE RUN"
                if st.session_state.sandbox_preview
                else "REPLAYING"
                if playing
                else "COMPLETE"
                if cursor == total
                else "PAUSED"
            )
            st.html('<div class="workspace-step">02 / Review the result</div>')
            st.subheader(run.options.strategy)
            st.caption(
                f"{state} · {run.options.scenario} · {run.options.bars // 24} days "
                "· synthetic BTCUSDT"
            )
            columns = st.columns(5)
            roi = view["pnl"] / run.artifact.config.strategy.capital * 100
            columns[0].metric("Net P&L", f"{view['pnl']:+,.2f}", f"{roi:+.2f}%")
            columns[1].metric(
                "Equity", f"{run.artifact.config.strategy.capital + view['pnl']:,.2f}"
            )
            columns[2].metric("Max. drawdown", f"{view['drawdown'] * 100:.2f}%")
            columns[3].metric("Fills", len(view["fills"]))
            columns[4].metric("Fees", f"{view['fees']:,.2f}")
            equity_tab, price_tab, fills_tab, risk_tab, details_tab = st.tabs(
                ["Equity curve", "Price & fills", "Trade log", "Risk checks", "Run details"]
            )
            with equity_tab:
                st.caption("Portfolio value after fees and slippage · USDT")
                equity_chart(run, view)
            with price_tab:
                st.caption("Synthetic candles · ▲ buy / ▼ sell · next-opening fills")
                if view["candles"]:
                    price_chart(view)
                else:
                    st.info("Press Play replay or Next bar to reveal the first candle.")
            with fills_tab:
                if view["fills"]:
                    st.dataframe(pd.DataFrame(view["fills"]), hide_index=True, width="stretch")
                else:
                    st.info("No fills at this point. The strategy warms up before its first order.")
                with st.expander("Orders"):
                    st.dataframe(pd.DataFrame(view["orders"]), hide_index=True, width="stretch")
            with risk_tab:
                st.write(
                    f"Risk state: {'HALTED — daily loss guard' if view['halted'] else 'ARMED'}"
                )
                st.write(f"Cash: {view['cash']:,.2f} USDT · Position: {view['position']:+.6f} BTC")
                st.write(f"Unavailable warm-up signals: {view['unavailable']}")
                st.write(f"Rejected risk checks: {len(view['rejects'])}")
                if view["rejects"]:
                    st.dataframe(pd.DataFrame(view["rejects"]), hide_index=True, width="stretch")
                st.caption("A loss trip blocks new orders. Inventory stays marked; no forced exit.")
            with details_tab:
                st.json(run.options.model_dump(mode="json"), expanded=False)
                st.caption(
                    f"Run {run.artifact.config.run_id} "
                    f"· source {run.artifact.context.code_commit[:12]} "
                    f"· development source dirty: {run.artifact.context.dirty}"
                )
                st.caption(
                    "Synthetic demo only. No registry writes, TEST access or real orders. "
                    "Short positions are simulated; borrowing, impact and queueing are unmodelled."
                )
                st.download_button(
                    "Download simulation",
                    run.export(),
                    file_name=f"{run.artifact.config.run_id}.json",
                    mime="application/json",
                )
            st.progress(
                cursor / total, text=f"{cursor} / {total} bars · replay a completed simulation"
            )
            buttons = st.columns([1.2, 1, 1, 1])
            if buttons[0].button("Pause" if playing else "Play replay", width="stretch"):
                if st.session_state.sandbox_cursor == total:
                    st.session_state.sandbox_cursor = 0
                st.session_state.sandbox_preview = False
                st.session_state.sandbox_playing = not playing
                st.rerun()
            if buttons[1].button("Next bar", disabled=playing, width="stretch"):
                st.session_state.sandbox_preview = False
                st.session_state.sandbox_cursor = min(total, cursor + 1)
                st.rerun()
            if buttons[2].button("Reset replay", width="stretch"):
                st.session_state.sandbox_cursor = 0
                st.session_state.sandbox_playing = False
                st.session_state.sandbox_preview = False
                st.rerun()
            buttons[3].selectbox(
                "Replay speed",
                [1, 4, 12],
                index=1,
                key="sandbox_speed",
                format_func=lambda n: f"{n} bars / tick",
                label_visibility="collapsed",
            )
            st.caption(
                "Replay advances every 0.5 seconds. "
                "Generated-price performance does not establish an eligible alpha."
            )

        playback()


def equity_chart(run: DemoRun, view: dict[str, Any]) -> None:
    st.vega_lite_chart(
        pd.DataFrame(view["equity"]),
        {
            "height": 300,
            "layer": [
                {
                    "mark": {
                        "type": "area",
                        "line": {"color": "#57dbc0"},
                        "color": "#57dbc0",
                        "opacity": 0.14,
                    },
                    "encoding": {
                        "x": {"field": "time", "type": "temporal", "title": None},
                        "y": {
                            "field": "equity",
                            "type": "quantitative",
                            "title": None,
                            "scale": {"zero": False},
                            "stack": None,
                        },
                        "y2": {"datum": float(run.artifact.config.strategy.capital)},
                        "tooltip": [
                            {"field": "time", "type": "temporal"},
                            {"field": "equity", "title": "Equity", "format": ",.2f"},
                        ],
                    },
                },
                {
                    "mark": {"type": "rule", "color": "#8797ad", "strokeDash": [4, 4]},
                    "encoding": {"y": {"datum": float(run.artifact.config.strategy.capital)}},
                },
            ],
            "config": {
                "background": "transparent",
                "view": {"stroke": None},
                "axis": {"gridColor": "#233044", "gridOpacity": 0.5},
            },
        },
        width="stretch",
    )
