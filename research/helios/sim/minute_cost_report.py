"""Cost reality from retained evidence only; no candidate evaluation or selection."""

import json
from math import fsum, isclose, isfinite
from pathlib import Path
from typing import Any

from sqlalchemy import Engine

from helios.data.binance import sha256_file
from helios.registry.results import get_result
from helios.sim.report import verified_evidence


def summarize(evidence: dict[str, Any]) -> dict[str, Any]:
    if evidence["protocol"]["definition"]["horizon_family"] != "H-MINUTE":
        raise ValueError("cost reality requires minute evidence")
    if evidence["status"] == "INVALID":
        return dict(status="INVALID", curve=[], gross=None, cost=None, net=None)
    common = [
        row
        for row in evidence["series"]
        if all(row[k] is not None for k in ("gross_return", "cost", "net_return"))
    ]
    if not common:
        raise ValueError("no paired gross/cost/net observations")
    gross, cost, net = (
        fsum(float(row[key]) for row in common) for key in ("gross_return", "cost", "net_return")
    )
    if not all(map(isfinite, (gross, cost, net))) or not isclose(
        gross - cost, net, rel_tol=1e-10, abs_tol=1e-9
    ):
        raise ValueError("saved gross minus costs does not reconcile to net")
    curve = [
        dict(
            multiplier=p["multiplier"],
            cost_bps=p["cost_bps"],
            total_cost=p["total_cost"],
            annual_sharpe=p["metrics"]["metrics"]["annual_sharpe"],
            total_return=p["metrics"]["metrics"]["total_return"],
        )
        for p in evidence["costs"]["points"]
    ]
    base = next(p for p in curve if p["multiplier"] == 1)
    if [p["multiplier"] for p in curve] != [0.5, 1, 2, 3, 4]:
        raise ValueError("retain all five fixed stress points")
    turnover = cost / (base["cost_bps"] / 10_000)
    return dict(
        status=evidence["status"],
        n_paired=len(common),
        gross=gross,
        cost=cost,
        net=net,
        cost_bps=base["cost_bps"],
        gross_bps_per_turnover=None if turnover == 0 else gross / turnover * 10_000,
        curve=curve,
    )


def render(rows: list[dict[str, Any]], destination: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    measured = [r for r in rows if r["gross"] is not None]
    for row in measured:
        axes[1].plot(
            [p["multiplier"] for p in row["curve"]],
            [p["annual_sharpe"] for p in row["curve"]],
            ".-",
            label=row["alpha_id"],
        )
    labels = [r["alpha_id"] for r in measured]
    axes[0].barh(labels, [r["gross_bps_per_turnover"] or 0 for r in measured], label="Gross edge")
    axes[0].axvline(12, color="red", linestyle="--", label="Accepted BTC cost: 12 bps")
    axes[0].axvline(0, color="gray", linewidth=0.5)
    axes[0].set(xlabel="Gross arithmetic return / turnover (bps)", title="Gross edge versus cost")
    axes[0].legend()
    axes[1].axhline(0, color="gray", linewidth=0.5)
    axes[1].set(
        xlabel="Fee + slippage multiplier",
        ylabel="Annual minute Sharpe",
        title="Saved fixed cost stress; unchanged execution",
    )
    axes[1].legend(fontsize=8, ncol=2)
    fig.suptitle("BTCUSDT minute VALID — all candidates REJECTED; no TEST or promotion")
    fig.tight_layout()
    fig.savefig(destination / "minute_cost_reality.svg")
    fig.savefig(destination / "minute_cost_reality.png", dpi=140)
    plt.close(fig)
    svg = destination / "minute_cost_reality.svg"
    svg.write_text("\n".join(line.rstrip() for line in svg.read_text().splitlines()) + "\n")


def build_report(engine: Engine, manifest: Path, destination: Path) -> Path:
    outcomes = json.loads(manifest.read_text())
    expected = {f"minute_b{i}" for i in range(3)} | {f"minute_h{i:02d}" for i in range(1, 9)}
    if len(outcomes) != 11 or {r["alpha_id"] for r in outcomes} != expected:
        raise ValueError("retain the complete eleven-candidate minute round")
    rows = []
    with engine.connect() as connection:
        for outcome in outcomes:
            result = get_result(connection, outcome["run_id"])
            if (
                result.evaluation_json is None
                or result.split.value != "valid"
                or result.dirty
                or result.evaluation_json["artifact_sha256"] != outcome["artifact_sha256"]
            ):
                raise ValueError("cost report requires unchanged clean VALID results")
            rows.append(
                summarize(verified_evidence(result))
                | dict(
                    alpha_id=result.alpha_id,
                    run_id=result.run_id,
                    code_commit=result.code_commit,
                    artifact_sha256=outcome["artifact_sha256"],
                )
            )
    destination.mkdir(parents=True, exist_ok=False)
    render(rows, destination)
    path = destination / "minute_cost_reality.json"
    path.write_text(
        json.dumps(
            dict(
                manifest_sha256=sha256_file(manifest),
                rows=rows,
                convention=(
                    "arithmetic reference P&L; paired gross/net periods, not compounded wealth"
                ),
                limitations=[
                    "Single coin, VALID development evidence, all candidates rejected.",
                    "No resimulation, search, selection, TEST access or promotion.",
                    "Curves use every retained 0.5/1/2/3/4x stress point.",
                ],
                plot_sha256={
                    name: sha256_file(destination / name)
                    for name in ("minute_cost_reality.svg", "minute_cost_reality.png")
                },
            ),
            indent=2,
            allow_nan=False,
        )
        + "\n"
    )
    return path
