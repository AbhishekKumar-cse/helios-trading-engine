"""Crypto-style configuration and causal playback over retained NSE backtests."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from helios.common.lineage import PROJECT_ROOT
from helios.dashboard.nse_backtest import (
    FIRST,
    LAST,
    STRATEGIES,
    DatasetChoice,
    NseOptions,
    datasets,
    read_run,
    run_backtest,
)
from helios.dashboard.nse_replay import replay_view
from helios.dashboard.simulation_page import price_chart


def _signature(dataset: DatasetChoice, options: NseOptions) -> str:
    return dataset.manifest_sha256 + dataset.interval + options.model_dump_json()


def _equity_chart(view: dict[str, Any], capital: Decimal) -> None:
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
                        "y2": {"datum": float(capital)},
                        "tooltip": [
                            {"field": "time", "type": "temporal"},
                            {"field": "equity", "format": ",.2f"},
                        ],
                    },
                },
                {
                    "mark": {"type": "rule", "color": "#8797ad", "strokeDash": [4, 4]},
                    "encoding": {"y": {"datum": float(capital)}},
                },
            ],
            "config": {"background": "transparent", "view": {"stroke": None}},
        },
        width="stretch",
    )


def render_nse_backtest(root: Path = PROJECT_ROOT) -> None:
    st.caption("NSE BACKTEST · actual retained prices · simulated execution · INR")
    try:
        choices = datasets(root)
    except (OSError, ValueError, KeyError):
        st.error("The retained NSE dataset list could not be verified.")
        return
    if not choices:
        st.info("Download a supported minute or hourly snapshot to enable NSE backtesting.")
        return
    settings, results = st.columns([1, 2.65], gap="large")
    with settings:
        with st.container(border=True):
            st.html('<div class="workspace-step">01 / Configure your idea</div>')
            run_button = st.empty()
            dataset = st.selectbox(
                "Backtest timeframe",
                choices,
                key="nse_dataset",
                format_func=lambda d: "Minute (1m)" if d.interval == "1m" else "Hourly (1h)",
            )
            symbol = st.selectbox(
                "Backtest company",
                dataset.symbols,
                index=dataset.symbols.index("RELIANCE") if "RELIANCE" in dataset.symbols else 0,
                key=f"nse_symbol_{dataset.interval}",
            )
            strategy = st.selectbox("NSE strategy", STRATEGIES, key="nse_strategy")
            maximum = 60 if dataset.interval == "1m" else 4
            lookback = st.slider(
                "Lookback / bars",
                1,
                maximum,
                5 if maximum == 60 else 1,
                key=f"nse_lookback_{dataset.interval}",
                help="Completed closes only; lookbacks reset each session.",
            )
            relation = ">" if strategy == "Trend following" else "<"
            st.caption("Signal preview · template notation")
            st.code(
                "long during session"
                if strategy == "Long during session"
                else f"long if close {relation} lag(close, {lookback}) else flat",
                language="text",
                wrap_lines=True,
            )
            selected = st.date_input(
                "Backtest dates",
                value=(date(2026, 1, 12), date(2026, 1, 16)),
                min_value=FIRST,
                max_value=LAST,
                key="nse_dates",
            )
            capital = st.number_input(
                "Starting capital / INR",
                min_value=1000,
                max_value=10000000,
                value=100000,
                step=1000,
                key="nse_capital",
            )
            with st.expander("Costs, position size & assumptions"):
                allocation = st.slider("NSE allocation / %", 5, 80, 10, 5, key="nse_allocation")
                doubled = st.checkbox(
                    "Compare doubled transaction costs", value=True, key="nse_costs"
                )
                st.caption(
                    "Minute: retained brokerage/tax model + 5 bps slippage per side. "
                    "Hourly: 15 bps fee + 5 bps slippage per side."
                )
                st.caption(
                    "Whole shares, next-opening fills, flat at session end. "
                    "Ending cash carries into the next replayed session."
                )
            st.caption("Actual historical data · Jan 9–Jun 30, 2026 · up to 31 days per run.")
            options = None
            try:
                if isinstance(selected, tuple) and len(selected) == 2:
                    options = NseOptions(
                        symbol=symbol,
                        start=selected[0],
                        end=selected[1],
                        strategy=strategy,
                        lookback=lookback,
                        capital=Decimal(capital),
                        allocation_pct=allocation,
                        compare_costs=doubled,
                    )
                else:
                    st.info("Choose both the start and end dates.")
            except ValueError:
                st.info("Choose an ordered range of at most 31 days within the development window.")
            submitted = run_button.button(
                "Run NSE backtest",
                type="primary",
                width="stretch",
                icon=":material/play_arrow:",
                disabled=options is None,
                key="nse_run",
            )
    with results:
        st.html('<div class="workspace-step">02 / Review the result</div>')
        if submitted and options is not None:
            indicator = st.progress(0.0, text="Verifying retained source data…")

            def update_progress(value: float, message: str) -> None:
                indicator.progress(value, text=message)

            try:
                directory = run_backtest(dataset, options, progress=update_progress)
                st.session_state.nse_backtest_directory = str(directory)
                st.session_state.nse_backtest_signature = _signature(dataset, options)
                st.session_state.nse_playing = False
                st.session_state.nse_cursor = None
            except ValueError as exc:
                st.error(str(exc))
            except Exception:
                st.error("Backtest failed. Previous runs are kept; check data and file access.")
            finally:
                indicator.empty()
        if "nse_backtest_directory" not in st.session_state:
            with st.container(border=True):
                st.subheader("Your NSE backtest")
                st.write("Choose a company and strategy on the left, then run your backtest.")
                st.caption("Equity, candlesticks, trades and replay controls will appear here.")
            return
        if options is None or st.session_state.nse_backtest_signature != _signature(
            dataset, options
        ):
            st.info("Settings changed. Showing the last completed run; run again to update.")
        try:
            directory = Path(st.session_state.nse_backtest_directory)
            protocol, result, observed = read_run(directory)
        except (OSError, ValueError, KeyError):
            st.error("The saved backtest failed integrity verification.")
            return
        if st.session_state.get("nse_cursor") is None:
            st.session_state.nse_cursor = len(observed)
        st.session_state.setdefault("nse_playing", False)

        @st.fragment(run_every=0.5 if st.session_state.nse_playing else None)
        def playback() -> None:
            total = len(observed)
            if st.session_state.nse_playing:
                st.session_state.nse_cursor = min(
                    total, st.session_state.nse_cursor + st.session_state.get("nse_speed", 4)
                )
                if st.session_state.nse_cursor == total:
                    st.session_state.nse_playing = False
                    st.rerun()
            cursor = st.session_state.nse_cursor
            _render_replay(
                directory,
                protocol,
                result,
                observed,
                replay_view(protocol, result, observed, cursor),
                cursor,
            )

        playback()


def _render_replay(
    directory: Path,
    protocol: dict[str, Any],
    result: dict[str, Any],
    observed: pd.DataFrame,
    view: dict[str, Any],
    cursor: int,
) -> None:
    settings = protocol["options"]
    total = len(observed)
    playing = st.session_state.nse_playing
    state = "REPLAYING" if playing else "COMPLETE" if cursor == total else "PAUSED"
    st.subheader(f"{settings['symbol']} · {settings['strategy']}")
    st.caption(
        f"{state} · {settings['start']} to {settings['end']} "
        f"· {protocol['interval']} · actual NSE data"
    )
    capital = Decimal(settings["capital"])
    columns = st.columns(5)
    columns[0].metric(
        "Net P&L / INR", f"{view['pnl']:+,.2f}", f"{view['pnl'] / capital * 100:+.2f}%"
    )
    columns[1].metric("Equity / INR", f"{view['current_equity']:,.2f}")
    columns[2].metric("Max. drawdown", f"{view['drawdown'] * 100:.2f}%")
    columns[3].metric("Simulated fills", len(view["fills"]))
    columns[4].metric("Cash fees / INR", f"{view['fees']:,.2f}")
    tabs = st.tabs(
        ["Equity curve", "Price & fills", "Trade log", "Session coverage", "Run details"]
    )
    with tabs[0]:
        st.caption("Portfolio value after fees and slippage · INR")
        _equity_chart(view, capital)
        if cursor == total and "2" in result["scenarios"]:
            st.dataframe(
                pd.DataFrame(
                    [
                        dict(
                            Costs="Normal" if k == "1" else "Doubled",
                            **{
                                "Net P&L / INR": float(v["summary"]["net_pnl"]),
                                "Return %": v["summary"]["net_return"] * 100,
                                "Cash fees / INR": float(v["summary"]["fees"]),
                            },
                        )
                        for k, v in result["scenarios"].items()
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
    with tabs[1]:
        st.caption("Observed NSE candles · ▲ buy / ▼ sell · next-opening fills")
        if view["candles"]:
            price_chart(view, price_title="Observed price / INR")
        else:
            st.info("Press Play replay or Next bar to reveal the first candle.")
    with tabs[2]:
        fills = pd.DataFrame(view["fills"])
        if fills.empty:
            st.info("No fills at this point. The strategy may be warming up or staying flat.")
        else:
            fills["Time / IST"] = pd.to_datetime(
                fills.timestamp, unit="us", utc=True
            ).dt.tz_convert("Asia/Kolkata")
            st.dataframe(
                fills[["Time / IST", "side", "quantity", "price", "fee", "order_id"]],
                hide_index=True,
                width="stretch",
            )
            st.download_button(
                "Download trade CSV",
                fills.to_csv(index=False),
                file_name=f"{result['run_id']}_bar{cursor}_trades.csv",
                mime="text/csv",
            )
        with st.expander("Orders & session charges"):
            st.dataframe(pd.DataFrame(view["orders"]), hide_index=True, width="stretch")
            if view["charges"]:
                st.dataframe(pd.DataFrame(view["charges"]), hide_index=True, width="stretch")
                st.caption("Session charges are included in total fees, alongside per-fill fees.")
    with tabs[3]:
        st.write(f"Cash: INR {view['cash']:,.2f} · Position: {view['position']} shares")
        st.caption(
            f"Completed sessions: {len(view['daily'])} / "
            f"{len(protocol['expected_sessions'])} expected"
        )
        if view["daily"]:
            st.dataframe(pd.DataFrame(view["daily"]), hide_index=True, width="stretch")
        if protocol["excluded_sessions"]:
            st.warning("Excluded sessions have unknown returns, not zero returns.")
            st.dataframe(
                pd.DataFrame(protocol["excluded_sessions"]), hide_index=True, width="stretch"
            )
        st.caption("Complete screened sessions only. Coverage is selected retrospectively.")
    with tabs[4]:
        st.json(settings, expanded=False)
        st.caption(
            f"Run {result['run_id']} · source {protocol['code_commit'][:12]} "
            f"· dirty {protocol['dirty']}"
        )
        st.caption(
            "Actual historical observations, simulated fills. No promotion, TEST or real orders."
        )
        if cursor == total:
            st.download_button(
                "Download NSE backtest",
                (directory / "result.json").read_bytes(),
                file_name=f"{result['run_id']}.json",
                mime="application/json",
            )
        else:
            st.caption(
                "The full report and cost comparison are available at the end of the replay."
            )
        st.caption(f"Source snapshot: {Path(protocol['dataset']).name}")
    st.progress(
        cursor / total, text=f"{cursor} / {total} observed bars · replay a completed backtest"
    )
    buttons = st.columns([1.2, 1, 1, 1])
    if buttons[0].button("Pause" if playing else "Play replay", width="stretch", key="nse_play"):
        if cursor == total:
            st.session_state.nse_cursor = 0
        st.session_state.nse_playing = not playing
        st.rerun()
    if buttons[1].button("Next bar", disabled=playing, width="stretch", key="nse_next"):
        st.session_state.nse_cursor = min(total, cursor + 1)
        st.rerun()
    if buttons[2].button("Reset replay", width="stretch", key="nse_reset"):
        st.session_state.nse_cursor = 0
        st.session_state.nse_playing = False
        st.rerun()
    buttons[3].selectbox(
        "Replay speed",
        [1, 4, 12, 60],
        index=1,
        key="nse_speed",
        format_func=lambda n: f"{n} bars / tick",
        label_visibility="collapsed",
    )
    st.caption(
        "Only reached bars, fills and charges are shown. "
        "Development replay; certification still blocks promotion."
    )
