"""Read-only reconciliation of a completed NSE hourly or minute round (no refit)."""

import argparse
import json
import math
from collections import Counter, defaultdict
from dataclasses import asdict
from decimal import Decimal, localcontext
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text

from helios.common.db import get_engine
from helios.common.lineage import PROJECT_ROOT
from helios.data.equities import sha256
from helios.data.snapshots import SnapshotFile, compute_snapshot_id
from helios.equities.pipeline import registry_fingerprint
from helios.registry.results import get_result
from helios.sim.fitness import fitness
from helios.sim.metrics import return_metrics
from helios.sim.report import generate_report

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("round_id")
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
root = PROJECT_ROOT / "reports_out/equity_research" / args.round_id
summary = json.loads((root / "summary.json").read_text())
protocol = json.loads((root / "protocol.json").read_text())
snapshot = json.loads((root / "snapshot.json").read_text())
prereg = json.loads((root / "preregistration.json").read_text())
assert sha256(root / "protocol.json") == summary["protocol_sha256"]
attempts = len(prereg["attempts"])
assert len(summary["results"]) == attempts
assert {(r["symbol"], r["candidate"]) for r in summary["results"]} == {
    (r["symbol"], r["candidate"]) for r in prereg["attempts"]
}
slots = 375 if summary.get("interval") == "1m" else 7
full_slots = 375 if slots == 375 else 6
assert len({(r["symbol"], r["candidate"]) for r in summary["results"]}) == attempts
assert Counter(r["candidate"] for r in summary["results"]) == Counter(
    r["candidate"] for r in prereg["attempts"]
)
assert len({r["symbol"] for r in summary["results"]}) == len(
    {r["symbol"] for r in prereg["attempts"]}
)
assert len({r["run_id"] for r in summary["results"]}) == attempts
assert compute_snapshot_id([SnapshotFile(**f) for f in snapshot["files"]]) == summary["snapshot_id"]
post_round_source_changes = {}
for name, digest in protocol["source_hashes"].items():
    assert sha256(root / "source" / name) == digest
    current = sha256(PROJECT_ROOT / name)
    if current != digest:
        post_round_source_changes[name] = dict(archived=digest, current=current)
for item in snapshot["files"]:
    assert sha256(PROJECT_ROOT / item["path"]) == item["sha256"]
calibration = json.loads((root / "ml/calibration.json").read_text())
assert sha256(root / "ml/model.txt") == summary["model_hash"] == calibration["model_sha256"]
assert sha256(root / "ml/calibration.json") == summary["calibration_hash"]
assert not calibration["valid_observations_used_for_fit_or_calibration"]
assert not calibration["test_access"]
assert calibration["train_last_label"] < calibration["calibration_first_feature"]
assert calibration["calibration_last_label"].startswith("2025-12-31")
inputs = {}
for path in sorted((root / "inputs").glob("*.parquet")):
    if path.stem not in {row["symbol"] for row in summary["results"]}:
        continue
    frame = pd.read_parquet(path)
    assert frame.session_date.max() <= "2026-06-30"
    inputs[path.stem] = {int(r.open_time): Decimal(str(r.open)) for r in frame.itertuples()}
engine = get_engine()
assert registry_fingerprint(engine) == summary["registry_before"] == summary["registry_after"]
assert summary["crypto_unchanged"] and summary["promoted"] == summary["test_accesses"] == 0
fill_ids = set()
fills_count = sessions_count = 0
fees_total = Decimal(0)
coverage = []
invalid = Counter()
by_candidate = defaultdict(list)
with engine.connect() as connection, localcontext() as context:
    connection.execute(text("SET TRANSACTION READ ONLY"))
    context.prec = 100
    experiment_ids = [r["experiment_id"] for r in summary["results"]]
    timestamps = connection.execute(
        text("SELECT max(pre_registered_at) FROM experiments WHERE experiment_id = ANY(:ids)"),
        {"ids": experiment_ids},
    ).scalar_one()
    first_result = connection.execute(
        text("SELECT min(created_at) FROM alpha_results WHERE experiment_id = ANY(:ids)"),
        {"ids": experiment_ids},
    ).scalar_one()
    assert timestamps < first_result
    states = connection.execute(
        text(
            "SELECT status, count(*) FROM experiments "
            "WHERE experiment_id = ANY(:ids) GROUP BY status"
        ),
        {"ids": experiment_ids},
    ).all()
    assert states == [("finished", attempts)]
    for row in summary["results"]:
        stored = get_result(connection, row["run_id"])
        artifact = Path(row["artifact"])
        assert stored.experiment_id == row["experiment_id"]
        assert stored.snapshot_id == summary["snapshot_id"]
        assert stored.status.value == row["status"]
        assert (
            stored.evaluation_json["artifact_sha256"] == row["artifact_sha256"] == sha256(artifact)
        )
        assert stored.split.value == "valid" and stored.dirty
        evidence = json.loads(artifact.read_text())
        assert evidence["gates"]["outcomes"][6]["gate"] == "G7"
        assert not stored.gate_results["G7"]
        assert not evidence["test_access"] and evidence["is_simulated"]
        assert evidence["source_hashes"] == protocol["source_hashes"]
        coverage.append(evidence["coverage"]["fraction"])
        assert (
            evidence["coverage"]["complete"] + len(evidence["coverage"]["excluded"])
            == evidence["coverage"]["expected"]
        )
        assert (
            stored.gate_results
            == row["gates"]
            == {g["gate"]: g["passed"] for g in evidence["gates"]["outcomes"]}
        )
        if row["status"] == "INVALID":
            assert not evidence["series"] and not evidence["fills"]
            assert stored.sharpe is stored.fitness is stored.annual_return is None
            invalid.update(evidence["validity"]["reasons"])
            continue
        assert row["status"] == "REJECTED"
        days = {r["day"]: r for r in evidence["series"]}
        assert len(days) == evidence["coverage"]["complete"] == stored.periods
        sessions_count += len(days)
        day_fills = defaultdict(list)
        day_snapshots = defaultdict(list)
        for point in evidence["ledger_snapshots"]:
            day = str(
                pd.Timestamp(point["timestamp"], unit="us", tz="UTC")
                .tz_convert("Asia/Kolkata")
                .date()
            )
            assert point["quote_asset"] == "INR"
            day_snapshots[day].append(point)
        for fill in evidence["fills"]:
            assert fill["fill_id"] not in fill_ids
            fill_ids.add(fill["fill_id"])
            quantity, price, fee = map(Decimal, (fill["quantity"], fill["price"], fill["fee"]))
            assert quantity > 0 and quantity == quantity.to_integral_value()
            assert fill["symbol"] == row["symbol"] and fill["fee_asset"] == "INR"
            assert fill["mode"] == "BACKTEST"
            timestamp = int(fill["timestamp"])
            opening = inputs[row["symbol"]][timestamp]
            sign = 1 if fill["side"] == "BUY" else -1
            assert abs(price - opening * (1 + sign * Decimal(".0005"))) <= Decimal("1e-18")
            assert abs(fee - quantity * price * Decimal(".0015")) <= Decimal("1e-18")
            local = pd.Timestamp(timestamp, unit="us", tz="UTC").tz_convert("Asia/Kolkata")
            assert (
                (10 <= local.hour <= 15 and local.minute == 15)
                if slots == 7
                else (556 <= local.hour * 60 + local.minute <= 929)
            )
            day_fills[str(local.date())].append(fill)
            fills_count += 1
        total_fees = Decimal(0)
        for day, measured in days.items():
            cash, position, fees, notional = Decimal(100000), Decimal(0), Decimal(0), Decimal(0)
            for fill in day_fills[day]:
                quantity, price, fee = map(Decimal, (fill["quantity"], fill["price"], fill["fee"]))
                sign = 1 if fill["side"] == "BUY" else -1
                position += sign * quantity
                assert position >= 0
                cash -= sign * quantity * price + fee
                fees += fee
                notional += quantity * price
            assert position == 0 and len(day_snapshots[day]) == slots
            final = day_snapshots[day][-1]
            assert abs(cash - Decimal(final["equity"])) < Decimal("1e-12")
            assert Decimal(final["cash"]) == Decimal(final["equity"])
            assert abs(fees - Decimal(final["fees"])) < Decimal("1e-12")
            assert abs(fees - Decimal(measured["fees"])) < Decimal("1e-12")
            assert math.isclose(
                float((cash - Decimal(100000)) / Decimal(100000)),
                measured["net_return"],
                abs_tol=1e-12,
            )
            assert math.isclose(
                float(notional / Decimal(100000)), measured["turnover"], abs_tol=1e-12
            )
            assert measured["n_fills"] == len(day_fills[day])
            total_fees += fees
        assert abs(total_fees - Decimal(evidence["fees_total_inr"])) < Decimal("1e-10")
        fees_total += total_fees
        returns = [point["net_return"] for point in evidence["series"]]
        recalculated = asdict(return_metrics(returns, periods_per_year=252))
        for name, value in recalculated.items():
            measured = evidence["diagnostics"]["base"]["metrics"][name]
            assert value == measured or math.isclose(value, measured, rel_tol=1e-12, abs_tol=1e-12)
        stressed = asdict(return_metrics(evidence["stress_session_returns"], periods_per_year=252))
        for name, value in stressed.items():
            measured = evidence["costs"]["points"][1]["metrics"]["metrics"][name]
            assert value == measured or math.isclose(value, measured, rel_tol=1e-12, abs_tol=1e-12)
        turnover = float(np.mean([point["turnover"] / full_slots for point in evidence["series"]]))
        fit = fitness(recalculated["annual_sharpe"], recalculated["annual_return"], turnover)
        monthly = defaultdict(float)
        for point in evidence["series"]:
            monthly[point["day"][:7]] += point["net_return"]
        positive_fraction = sum(value > 0 for value in monthly.values()) / len(monthly)
        gates = evidence["protocol"]["gates"]

        def above(value, threshold):
            return value is not None and value > threshold

        assert stored.gate_results == dict(
            G1=above(recalculated["annual_sharpe"], gates["sharpe_min"]),
            G2=above(fit, gates["fitness_min"]),
            G3=gates["turnover_min"] < turnover < gates["turnover_max"],
            G4=True,
            G5=positive_fraction > gates["stability_min_positive_fraction"],
            G6=above(stressed["annual_sharpe"], gates["cost_stress_sharpe_min"]),
            G7=False,
            G8=evidence["coverage"]["fraction"] >= 0.9,
        )
        for measured, retained in (
            (recalculated["annual_sharpe"], stored.sharpe),
            (recalculated["annual_return"], stored.annual_return),
            (turnover, stored.turnover),
            (fit, stored.fitness),
            (stressed["annual_sharpe"], stored.cost_stress_sharpe),
        ):
            assert (measured is retained is None) or math.isclose(
                measured, float(retained), abs_tol=1e-9
            )
        by_candidate[row["candidate"]].append(recalculated["total_return"])
        if row["symbol"] == "RELIANCE":
            html_path = generate_report(
                stored, output_root=root / "verified_html" / row["candidate"]
            )
            assert "NSE conditional" in html_path.read_text()
result = dict(
    round_id=summary["round_id"],
    snapshot_id=summary["snapshot_id"],
    protocol_sha256=summary["protocol_sha256"],
    source_manifest_verified=True,
    post_round_source_changes=post_round_source_changes,
    preregistered_before_first_valid_pnl=True,
    attempts=attempts,
    symbols=len({row["symbol"] for row in summary["results"]}),
    statuses=dict(Counter(r["status"] for r in summary["results"])),
    statuses_by_candidate={
        c: dict(Counter(r["status"] for r in summary["results"] if r["candidate"] == c))
        for c in sorted({row["candidate"] for row in summary["results"]})
    },
    invalid_reasons=dict(invalid),
    reconciled_base_fills=fills_count,
    reconciled_base_sessions=sessions_count,
    base_fees_inr=str(fees_total),
    fill_ids_unique=True,
    whole_share_long_only_flat_end=True,
    ledger_reconciliation=True,
    base_and_stress_metrics_verified=True,
    coverage_min=min(coverage),
    coverage_max=max(coverage),
    calibration=calibration,
    positive_conditional_results={
        c: sum(value > 0 for value in values) for c, values in by_candidate.items()
    },
    crypto_registry=summary["registry_after"],
    test_accesses=0,
    promoted=0,
    dirty=True,
)
with args.output.open("x") as handle:
    handle.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
print(json.dumps({k: v for k, v in result.items() if k != "calibration"}, indent=2))
