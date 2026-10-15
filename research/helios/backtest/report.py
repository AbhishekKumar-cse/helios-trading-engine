"""Hash-verified execution/accounting reports; never rerun the backtest (150)."""

import hashlib
import html
import json
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, text

from helios.backtest.runner import OUTPUT, BacktestArtifact
from helios.common.config import config_hash
from helios.common.db import get_engine
from helios.common.lineage import git_commit, git_is_dirty
from helios.common.types import AlphaStatus, OrderState, Side
from helios.data.binance import sha256_file
from helios.sim.paper import rounded


class BacktestReportError(ValueError):
    pass


def verified_artifact(engine: Engine, run_id: str) -> tuple[BacktestArtifact, str]:
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT * FROM backtest_runs WHERE bt_run_id=:id"), {"id": run_id}
        ).one()
        if row.status != "finished" or not row.results_ref or row.mode != "BACKTEST":
            raise BacktestReportError("report requires a finished BACKTEST artifact")
        path = Path(row.results_ref)
        if sha256_file(path) != row.artifact_sha256:
            raise BacktestReportError("registered backtest artifact checksum mismatch")
        artifact = BacktestArtifact.model_validate_json(path.read_text())
        config, trace = artifact.config, artifact.trace
        if (
            config.run_id != run_id
            or config.snapshot_id != row.data_snapshot_id
            or config.experiment_id != row.experiment_id
            or config.seed != row.seed
            or config_hash(config) != row.config_hash
            or artifact.context.config_hash != row.config_hash
            or artifact.context.code_commit != row.code_commit
            or artifact.context.dirty != row.dirty
            or row.config_json != config.model_dump(mode="json")
        ):
            raise BacktestReportError("registered backtest source/config lineage mismatch")
        orders = connection.execute(
            text("""SELECT order_id,client_order_id,status,qty,
            filled_qty,remaining_qty FROM orders WHERE bt_run_id=:id ORDER BY order_id"""),
            {"id": run_id},
        ).all()
        expected = sorted(
            (
                o.order_id,
                o.request.client_order_id,
                o.state.value,
                o.request.quantity,
                o.filled_quantity,
                o.remaining_quantity,
            )
            for o in trace.orders
        )
        if [tuple(o) for o in orders] != expected:
            raise BacktestReportError("database orders differ from immutable artifact")
        fills = connection.execute(
            text("""SELECT f.fill_id,f.order_id,f.price,f.qty,f.fee
            FROM fills f JOIN orders o USING(order_id) WHERE o.bt_run_id=:id ORDER BY f.fill_id"""),
            {"id": run_id},
        ).all()
        expected_fills = sorted(
            (r.fill.fill_id, r.fill.order_id, r.fill.price, r.fill.quantity, r.fill.fee)
            for r in trace.reports
            if r.fill is not None
        )
        if [tuple(f) for f in fills] != expected_fills:
            raise BacktestReportError("database fills differ from immutable artifact")
        pnl = connection.execute(
            text("""SELECT ts,cash,realised,unrealised,fees
            FROM pnl_snapshots WHERE bt_run_id=:id ORDER BY ts"""),
            {"id": run_id},
        ).all()
        if [tuple(p) for p in pnl] != [
            (s.timestamp, s.cash, s.realized_pnl, s.unrealized_pnl, s.fees) for s in trace.snapshots
        ]:
            raise BacktestReportError("database PnL differs from immutable artifact")
    return artifact, str(row.artifact_sha256)


def accounting_summary(artifact: BacktestArtifact) -> dict[str, Any]:
    """Gross excludes explicit fees and modelled slippage at the same actual sizes.

    This is a fixed-fill accounting attribution, not a no-cost strategy rerun.
    Mark-to-market net uses observed closing proxies, retaining open inventory.
    """
    config, trace = artifact.config, artifact.trace
    if not trace.snapshots or not (
        len(trace.snapshots) == len(trace.positions) == len(trace.marks) == len(artifact.bars)
    ):
        raise BacktestReportError("incomplete accounting timeline")
    with localcontext() as context:
        context.prec = 100
        fills = [r.fill for r in trace.reports if r.fill is not None]
        opens = {bar.open_time: bar.open for bar in artifact.bars}
        slippage = Decimal(0)
        for fill in fills:
            if fill.timestamp not in opens:
                raise BacktestReportError("market fill has no recorded opening reference")
            signed = fill.quantity * (1 if fill.side is Side.BUY else -1)
            slippage += signed * (fill.price - opens[fill.timestamp])
        final = trace.snapshots[-1]
        net = final.realized_pnl + final.unrealized_pnl - final.fees
        execution_gross = final.realized_pnl + final.unrealized_pnl
        gross = execution_gross + slippage
        peak, peak_time = config.strategy.capital, config.start_us
        max_drawdown = max_drawdown_fraction = Decimal(0)
        max_duration = 0
        underwater = False
        net_series, gross_series, drawdown_series, exposure_series = [], [], [], []
        for bar, snapshot, position, mark in zip(
            artifact.bars, trace.snapshots, trace.positions, trace.marks, strict=True
        ):
            equity = snapshot.equity
            if abs(
                equity
                - config.strategy.capital
                - (snapshot.realized_pnl + snapshot.unrealized_pnl - snapshot.fees)
            ) > Decimal("2e-18"):
                raise BacktestReportError("saved snapshot does not reconcile")
            # Include the recovery observation in a completed drawdown's
            # duration before resetting its peak clock.
            if underwater:
                max_duration = max(max_duration, snapshot.timestamp - peak_time)
            if equity >= peak:
                peak, peak_time = equity, snapshot.timestamp
            drawdown = peak - equity
            underwater = drawdown > 0
            max_drawdown = max(max_drawdown, drawdown)
            max_drawdown_fraction = max(max_drawdown_fraction, drawdown / peak)
            max_duration = max(max_duration, snapshot.timestamp - peak_time)
            current_net = equity - config.strategy.capital
            # A close at time t precedes the next opening at t. Do not attribute
            # a next-opening fill to the preceding close when clocks are equal.
            slip_to_date = sum(
                (
                    f.quantity * (1 if f.side is Side.BUY else -1) * (f.price - opens[f.timestamp])
                    for f in fills
                    if f.timestamp < bar.close_time
                ),
                Decimal(0),
            )
            net_series.append(str(rounded(current_net)))
            gross_series.append(str(rounded(current_net + snapshot.fees + slip_to_date)))
            drawdown_series.append(str(rounded(drawdown)))
            exposure_series.append(str(rounded(position.quantity * mark)))
        turnover_notional = sum((f.quantity * f.price for f in fills), Decimal(0))
        max_exposure = max(abs(Decimal(v)) for v in exposure_series)
        result = dict(
            mode="BACKTEST",
            is_simulated=True,
            run_id=config.run_id,
            input_kind=config.data_kind,
            symbol=config.symbol,
            quote_asset="USDT",
            gross_pnl=str(rounded(gross)),
            execution_gross_pnl=str(rounded(execution_gross)),
            net_pnl=str(rounded(net)),
            realized_pnl=str(final.realized_pnl),
            unrealized_pnl=str(final.unrealized_pnl),
            fees=str(final.fees),
            slippage=str(rounded(slippage)),
            final_cash=str(final.cash),
            final_equity=str(final.equity),
            max_drawdown=str(rounded(max_drawdown)),
            max_drawdown_fraction=str(rounded(max_drawdown_fraction)),
            max_drawdown_duration_us=max_duration,
            max_gross_exposure=str(max_exposure),
            final_net_exposure=exposure_series[-1],
            traded_notional=str(rounded(turnover_notional)),
            turnover_over_initial_capital=str(rounded(turnover_notional / config.strategy.capital)),
            order_count=len(trace.orders),
            fill_count=len(fills),
            filled_order_count=sum(o.state is OrderState.FILLED for o in trace.orders),
            maker_fills=sum(f.liquidity == "MAKER" for f in fills),
            taker_fills=sum(f.liquidity == "TAKER" for f in fills),
            risk_rejections=sum(not decision.accepted for decision in trace.decisions),
            unavailable_signals=sum(s.status is not AlphaStatus.OK for s in artifact.signals),
            unexecuted_tail_intents=len(trace.tail),
            final_quantity=str(trace.positions[-1].quantity),
            mark_reference=config.mark_reference,
            net_series=net_series,
            gross_series=gross_series,
            drawdown_series=drawdown_series,
            exposure_series=exposure_series,
            per_coin=[
                dict(
                    symbol=config.symbol,
                    gross_pnl=str(rounded(gross)),
                    net_pnl=str(rounded(net)),
                    fees=str(final.fees),
                    slippage=str(rounded(slippage)),
                    final_quantity=str(trace.positions[-1].quantity),
                )
            ],
        )
    return result


def _plot(values: list[str], label: str, color: str = "#157467") -> str:
    data = [float(v) for v in values]
    low, high = min(data), max(data)
    span = high - low or 1
    step = max(1, len(data) // 900)
    indices = sorted(set(range(0, len(data), step)) | {len(data) - 1})
    points = " ".join(
        f"{20 + i / max(1, len(data) - 1) * 760:.2f},{145 - (data[i] - low) / span * 125:.2f}"
        for i in indices
    )
    return (
        f'<svg viewBox="0 0 800 180" role="img" aria-label="{html.escape(label)}">'
        f'<polyline points="{points}" stroke="{color}" stroke-width="2.5" fill="none"/>'
        f'<text x="20" y="174">{low:.6f} to {high:.6f} USDT · observed closes</text></svg>'
    )


def _table(headers: list[str], rows: list[list[object]]) -> str:
    def cells(tag: str, values: list[object]) -> str:
        return "".join(f"<{tag}>" + html.escape(_display(value)) + f"</{tag}>" for value in values)

    return (
        "<table><thead><tr>"
        + cells("th", list(headers))
        + "</tr></thead><tbody>"
        + "".join("<tr>" + cells("td", row) + "</tr>" for row in rows)
        + "</tbody></table>"
    )


def _display(value: object) -> str:
    if isinstance(value, Decimal) or (
        isinstance(value, str) and re.fullmatch(r"-?\d+\.\d+", value)
    ):
        return f"{Decimal(str(value)):,.6f}"
    return str(value)


def generate_backtest_report(
    run_id: str, *, engine: Engine | None = None, output_root: Path = OUTPUT
) -> Path:
    engine = get_engine() if engine is None else engine
    artifact, digest = verified_artifact(engine, run_id)
    summary = accounting_summary(artifact)
    config, trace = artifact.config, artifact.trace
    generation = dict(code_commit=git_commit(), dirty=git_is_dirty())
    evidence = dict(
        artifact_sha256=digest,
        source_commit=artifact.context.code_commit,
        config_hash=config_hash(config),
        report_source=generation,
        summary=summary,
    )
    encoded = json.dumps(evidence, sort_keys=True, indent=2, allow_nan=False).encode()
    summary_hash = hashlib.sha256(encoded).hexdigest()

    def esc(value: object) -> str:
        return html.escape(str(value))

    fills = [r.fill for r in trace.reports if r.fill is not None]
    notice = (
        "Synthetic correctness fixture. These values verify accounting, not market performance."
        if config.data_kind == "synthetic_csv"
        else "Historical simulated execution. No gate approval or promotion is established."
    )
    cards = "".join(
        f'<div class="metric"><span>{label}</span>'
        f"<strong>{esc(_display(summary[key]))}</strong></div>"
        for label, key in [
            ("Gross P&L / USDT", "gross_pnl"),
            ("Net P&L / USDT", "net_pnl"),
            ("Fees / USDT", "fees"),
            ("Slippage / USDT", "slippage"),
        ]
    )
    accounting = _table(
        ["Accounting", "USDT"],
        [
            [label, summary[key]]
            for label, key in [
                ("Realized P&L before fees", "realized_pnl"),
                ("Unrealized P&L", "unrealized_pnl"),
                ("Gross after slippage, before fees", "execution_gross_pnl"),
                ("Final cash", "final_cash"),
                ("Final equity", "final_equity"),
            ]
        ],
    )
    risk = _table(
        ["Risk and execution", "Value"],
        [
            [
                label,
                (
                    f"{Decimal(summary[key]) * 100:.4f}%"
                    if key == "max_drawdown_fraction"
                    else f"{Decimal(summary[key]) / Decimal(3_600_000_000):.2f} hours"
                    if key == "max_drawdown_duration_us"
                    else summary[key]
                ),
            ]
            for label, key in [
                ("Maximum drawdown / USDT", "max_drawdown"),
                ("Maximum drawdown / percent", "max_drawdown_fraction"),
                ("Longest drawdown", "max_drawdown_duration_us"),
                ("Maximum gross exposure / USDT", "max_gross_exposure"),
                ("Final signed exposure / USDT", "final_net_exposure"),
                ("Orders", "order_count"),
                ("Trade count (fill events)", "fill_count"),
                ("Filled orders", "filled_order_count"),
                ("Maker fills", "maker_fills"),
                ("Taker fills", "taker_fills"),
                ("Traded notional / USDT", "traded_notional"),
                ("Turnover / initial capital", "turnover_over_initial_capital"),
                ("Risk rejections", "risk_rejections"),
                ("Unavailable signals", "unavailable_signals"),
                ("Unexecuted tail intents", "unexecuted_tail_intents"),
            ]
        ],
    )
    trades = _table(
        ["UTC time", "Side", "Quantity", "Price / USDT", "Fee / USDT", "Liquidity"],
        [
            [
                (
                    datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=f.timestamp)
                ).isoformat(),
                f.side.value,
                f.quantity,
                f.price,
                f.fee,
                f.liquidity,
            ]
            for f in fills
        ],
    )
    coins = _table(
        ["Coin", "Gross / USDT", "Net / USDT", "Fees / USDT", "Slippage / USDT", "Final qty"],
        [
            [
                row[k]
                for k in ("symbol", "gross_pnl", "net_pnl", "fees", "slippage", "final_quantity")
            ]
            for row in summary["per_coin"]
        ],
    )
    page = f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>HELIOS BACKTEST · {esc(run_id)}</title><style>
body{{margin:0;background:#f4f6f7;color:#182d3a;font:15px/1.5 system-ui,sans-serif}}
main{{max-width:1120px;margin:40px auto;padding:0 24px}}h1{{font-size:32px;margin-bottom:4px}}
h2{{font-size:20px;margin:28px 0 12px}}.badge{{color:#17685c;font-weight:700;letter-spacing:.1em}}
.notice{{border-left:4px solid #c49834;background:#fff8df;padding:16px;margin:22px 0}}
.grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}}
.metric,.panel{{background:white;border:1px solid #dce4e8;border-radius:8px;padding:18px}}
.metric span{{display:block;color:#506978}}.metric strong{{font-size:24px;overflow-wrap:anywhere}}
.charts{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}svg{{width:100%;height:auto}}
svg text{{font-size:20px;fill:#536b77}}table{{border-collapse:collapse;width:100%;background:white}}
td,th{{text-align:left;padding:9px 12px;border-bottom:1px solid #dde5e9;overflow-wrap:anywhere}}
th{{background:#e7eef1}}.scroll{{overflow-x:auto}}code{{overflow-wrap:anywhere}}
.muted{{color:#536b77}}@media(max-width:760px){{.grid{{grid-template-columns:1fr 1fr}}
.charts{{grid-template-columns:1fr}}
main{{margin-top:20px;padding:0 14px}}}}
@media(max-width:500px){{.grid,.charts{{grid-template-columns:1fr}}}}
</style><main><div class="badge">HELIOS · BACKTEST · SIMULATED</div>
<h1>Bar backtest</h1><p class="muted">{esc(run_id)} · {esc(config.symbol)} ·
{esc(config.split.value.upper())}</p>
<div class="notice">{notice}</div><div class="grid">{cards}</div>
<div class="charts"><section class="panel"><h2>Net P&L</h2>
{_plot(summary["net_series"], "Net P&L")}</section>
<section class="panel"><h2>Drawdown</h2>
{_plot(summary["drawdown_series"], "Drawdown", "#a84e46")}</section>
<section class="panel"><h2>Gross P&L before costs</h2>
{_plot(summary["gross_series"], "Gross P&L")}</section>
<section class="panel"><h2>Signed exposure</h2>
{_plot(summary["exposure_series"], "Signed exposure", "#446d98")}</section></div>
<h2>Accounting</h2>{accounting}<h2>Risk and execution</h2>{risk}
<h2>Per coin</h2><div class="scroll">{coins}</div>
<h2>Recorded fills</h2><div class="scroll">{trades}</div>
<h2>Definitions and limits</h2><p>Gross P&L removes fees and recorded opening-price slippage at the
same actual fill sizes. Net includes both. This attribution does not rerun a no-cost strategy.
Drawdown uses net equity including initial capital; duration runs from peak to recovery or the
last observed close. Trade count means fill events. Open inventory remains marked without
forced liquidation. Marks use <code>{esc(config.mark_reference)}</code>,
not observed midpoint quotes.</p>
<p>Fill model: complete next-opening market fills. Queueing, impact, partial fills, latency,
and fill/latency sensitivity are unmodelled. No independent TEST result or promotion is claimed.</p>
<h2>Lineage</h2><p>Alpha <code>{esc(config.alpha_id)}@{config.alpha_version}</code> ·
seed {config.seed} ·
experiment {config.experiment_id} · source dirty: {artifact.context.dirty}</p>
<p>Source commit <code>{esc(artifact.context.code_commit)}</code><br>
Snapshot <code>{esc(config.snapshot_id)}</code>
<br>Config SHA-256 <code>{config_hash(config)}</code><br>Artifact SHA-256 <code>{digest}</code>
<br>Input SHA-256 <code>{esc(artifact.input_sha256)}</code><br>
Summary SHA-256 <code>{summary_hash}</code></p>
<p class="muted">Report source {esc(generation["code_commit"])} · dirty: {generation["dirty"]}.
Hash-verified saved evidence. No backtest or model fit was rerun.</p></main></html>"""
    folder = output_root / config.run_id
    folder.mkdir(parents=True, exist_ok=True)
    for filename, contents in [
        (f"summary-{summary_hash}.json", encoded),
        (f"report-{hashlib.sha256(page.encode()).hexdigest()}.html", page.encode()),
    ]:
        path = folder / filename
        if not path.exists():
            with path.open("xb") as handle:
                handle.write(contents)
        elif path.read_bytes() != contents:
            raise BacktestReportError("immutable report archive conflict")
    latest = folder / "report.html"
    latest.write_text(page, encoding="utf-8")
    return latest
