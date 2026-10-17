"""Standalone HTML reports from hash-verified registered evaluation artifacts (118)."""

from __future__ import annotations

import hashlib
import html
import json
import math
from collections.abc import Sequence
from pathlib import Path
from string import Template
from typing import Any

from helios.registry.api import ALPHA_ID
from helios.registry.results import AlphaResult

DEFAULT_REPORT_ROOT = Path(__file__).resolve().parents[3] / "reports_out"


class ReportError(ValueError):
    """Missing/changed evidence must not be presented as a registered result."""


def verified_evidence(result: AlphaResult) -> dict[str, Any]:
    metadata = result.evaluation_json
    if metadata is None:
        raise ReportError("legacy result has no registered evaluation artifact")
    path = Path(str(metadata["artifact"]))
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != metadata["artifact_sha256"]:
        raise ReportError("registered artifact SHA-256 mismatch")
    data: dict[str, Any] = json.loads(raw)
    if data["status"] != result.status.value or data["snapshot_id"] != result.snapshot_id:
        raise ReportError("artifact status/snapshot mismatch")
    return data


def _number(value: Any, *, percent: bool = False) -> str:
    if value is None:
        return "N/A"
    return f"{float(value) * 100:.2f}%" if percent else f"{float(value):.4f}"


def _table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    return (
        "<table><thead><tr>"
        + "".join("<th>" + html.escape(str(h)) + "</th>" for h in headers)
        + "</tr></thead><tbody>"
        + "".join(
            "<tr>" + "".join("<td>" + html.escape(str(v)) + "</td>" for v in row) + "</tr>"
            for row in rows
        )
        + "</tbody></table>"
    )


def _plot(values: Sequence[float], title: str) -> str:
    if len(values) < 2:
        return '<p class="muted">Unavailable: no valid simulation series.</p>'
    if not all(math.isfinite(v) for v in values):
        raise ReportError("non-finite chart values")
    low, high = min(values), max(values)
    span = high - low or 1.0
    # Display-only sampling; metrics always use the complete recorded series.
    step = max(1, len(values) // 1000)
    indices = sorted(set(range(0, len(values), step)) | {len(values) - 1})
    points = " ".join(
        f"{30 + i / (len(values) - 1) * 940:.2f},{190 - (values[i] - low) / span * 160:.2f}"
        for i in indices
    )
    return (
        f'<svg viewBox="0 0 1000 220" role="img" '
        f'aria-label="{html.escape(title, quote=True)}">'
        f'<polyline points="{points}" fill="none" stroke="#37b99b" stroke-width="2"/>'
        f'<text x="30" y="215" fill="#63768b">{low:.4f} to {high:.4f}'
        " · chronological observed bars</text></svg>"
    )


def _cost_plot(points: Sequence[dict[str, Any]]) -> str:
    if not points:
        return '<p class="muted">Unavailable for INVALID simulation.</p>'
    x = [float(p["multiplier"]) for p in points]
    y = [float(p["metrics"]["metrics"]["total_return"]) for p in points]
    if not all(math.isfinite(v) for v in x + y):
        raise ReportError("non-finite cost curve")
    coordinates = " ".join(
        f"{30 + (a - min(x)) / (max(x) - min(x) or 1) * 940:.2f},"
        f"{190 - (b - min(y)) / (max(y) - min(y) or 1) * 160:.2f}"
        for a, b in zip(x, y, strict=True)
    )
    return (
        '<svg viewBox="0 0 1000 220" role="img" aria-label="Net P&amp;L cost curve">'
        f'<polyline points="{coordinates}" fill="none" stroke="#37b99b" stroke-width="2"/>'
        f'<text x="30" y="215">Cost multiplier {min(x)} to {max(x)}; '
        f"net total {min(y):.4f} to {max(y):.4f}</text></svg>"
    )


def generate_report(result: AlphaResult, *, output_root: Path = DEFAULT_REPORT_ROOT) -> Path:
    data = verified_evidence(result)
    validity = data["validity"]
    metrics = data.get("diagnostics", {}).get("base", {}).get("metrics", {})
    series = data.get("series", [])
    cumulative, drawdown = [], []
    total, peak = 0.0, 0.0
    for row in series:
        total += row["net_return"]
        peak = max(peak, total)
        cumulative.append(1 + total)
        drawdown.append(total - peak)
    gate_rows = [
        [
            g["gate"],
            "PASS" if g["passed"] else "FAIL",
            _number(g["value"]) if not isinstance(g["value"], bool) else str(g["value"]),
            g["comparison"],
            g["threshold"],
            g["reason"] or "—",
        ]
        for g in data["gates"]["outcomes"]
    ]
    costs = data.get("costs", {}).get("points", [])
    months = data.get("stability", {}).get("months", [])
    regimes = data.get("stability", {}).get("regimes", [])

    def escaped(value: object) -> str:
        return html.escape(str(value))

    if not ALPHA_ID.fullmatch(result.alpha_id):
        raise ReportError("unsafe alpha identifier")
    unavailable = '<p class="muted">Unavailable for INVALID simulation.</p>'
    notice = (
        "INVALID: "
        + ", ".join(validity["reasons"])
        + ". No performance conclusion is valid for this attempt."
        if result.status.value == "INVALID"
        else "Simulated reference exposure, net of configured costs. This is not live execution, "
        "compounded portfolio NAV or a promise of profitability."
    )
    if data.get("notice"):
        notice = str(data["notice"]) + " " + notice
    cost_table = (
        _table(
            ["Cost multiplier", "Total cost", "Net total", "Annual Sharpe"],
            [
                [
                    p["multiplier"],
                    _number(p["total_cost"]),
                    _number(p["metrics"]["metrics"]["total_return"]),
                    _number(p["metrics"]["metrics"]["annual_sharpe"]),
                ]
                for p in costs
            ],
        )
        if costs
        else ""
    )
    monthly_table = (
        _table(
            ["UTC month", "Periods", "Annual Sharpe", "Net total", "Incomplete month"],
            [
                [
                    m["month"],
                    m["metrics"]["n_periods"],
                    _number(m["metrics"]["annual_sharpe"]),
                    _number(m["metrics"]["total_return"]),
                    m["has_gaps"],
                ]
                for m in months
            ],
        )
        if months
        else unavailable
    )
    regime_table = (
        _table(
            ["Regime", "Periods", "Conditional Sharpe"],
            [
                [
                    r["name"],
                    r["n_periods"],
                    _number(None if r["metrics"] is None else r["metrics"]["annual_sharpe"]),
                ]
                for r in regimes
            ],
        )
        if regimes
        else unavailable
    )
    lineage = {
        "validity": validity,
        "source": data["source"],
        "snapshot_id": result.snapshot_id,
        "config_hash": result.config_hash,
        "gate_config_hash": data["gates"]["gate_config_hash"],
        "feature_provenance": data.get("feature_provenance", {}),
    }
    template = Template((Path(__file__).parent / "templates/alpha_report.html").read_text())
    content = template.substitute(
        alpha=escaped(result.alpha_id),
        version=result.version,
        split=escaped(result.split.value.upper()),
        status=escaped(result.status.value),
        run_id=escaped(result.run_id),
        symbol=escaped(validity["symbol"]),
        n_rows=f"{validity['n_rows']:,}",
        notice=escaped(notice),
        sharpe=_number(result.sharpe),
        fitness=_number(result.fitness),
        total=_number(metrics.get("total_return"), percent=True),
        turnover=_number(result.turnover, percent=True),
        equity_plot=_plot(cumulative, "Reference equity curve"),
        drawdown_plot=_plot(drawdown, "Additive net drawdown"),
        costs=_cost_plot(costs) + cost_table,
        months=monthly_table,
        regimes=regime_table,
        gates=_table(["Gate", "Outcome", "Value", "Rule", "Threshold", "Reason"], gate_rows),
        lineage=escaped(json.dumps(lineage, indent=2)),
        protocol=escaped(json.dumps(data["protocol"], indent=2)),
    )
    folder = output_root / result.alpha_id
    folder.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(content.encode()).hexdigest()
    archive = folder / f"{result.run_id}-{digest[:12]}.html"
    if not archive.exists():
        with archive.open("x", encoding="utf-8") as file:
            file.write(content)
    latest = folder / "report.html"
    temporary = folder / f".{result.run_id}.html.part"
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(latest)
    return latest
