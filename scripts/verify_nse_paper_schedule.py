"""Independently reconcile scheduled decisions, proxy fills and unchanged costs.

Complements verify_equity_round.py's registry, ledger, metric and gate audit.
Does not replay, fit, register results, release sources, or access TEST.
"""

import argparse
import json
import math
from collections import defaultdict
from decimal import Decimal, localcontext
from pathlib import Path

import pandas as pd

from helios.common.lineage import PROJECT_ROOT
from helios.data.equities import sha256, write_json
from helios.equities.charges import ChargeTrade, estimate_intraday_charges
from helios.equities.paper_features import feature_digest
from helios.features.runner import FeatureFrame


def state(frame, name):
    selected = frame.index[frame[name] == 1].tolist()
    if not selected:
        return None
    first, last = selected[0], selected[-1]
    assert selected == list(range(first, last + 1))
    assert 0 <= first < last + 1 <= 373
    return first, last + 1


def verify(round_id, output, training_records):
    if output.exists():
        raise ValueError("verification evidence must not be overwritten")
    root = PROJECT_ROOT / "reports_out/equity_research" / round_id
    summary = json.loads((root / "summary.json").read_text())
    protocol = json.loads((root / "protocol.json").read_text())
    assert sha256(root / "protocol.json") == summary["protocol_sha256"]
    assert summary["execution_policy"] == "paper_state_change_v1"
    assert summary["promoted"] == summary["test_accesses"] == 0
    snapshot_root = Path(protocol["source_snapshot"])
    assert sha256(snapshot_root / "manifest.json") == protocol["source_manifest_sha256"]
    source_manifest = json.loads((snapshot_root / "manifest.json").read_text())
    feature_protocol = json.loads((root / "feature_protocol.json").read_text())
    from helios.equities.rebuild import verified_file

    for symbol, expected in feature_protocol["source_files"].items():
        item = next(r for r in source_manifest["files"] if r["symbol"] == symbol)
        assert item["sha256"] == expected
        verified_file(snapshot_root, item["path"], expected)
    for row in feature_protocol["history_windows"]:
        assert len(set(row["prior_days"])) == 15 and max(row["prior_days"]) < row["day"]
    frames, states, counts = {}, {}, defaultdict(int)
    with localcontext() as context:
        context.prec = 100
        for result in summary["results"]:
            name, symbol = result["candidate"], result["symbol"]
            signals = pd.read_parquet(root / "inputs" / f"{symbol}_{name}_signals.parquet")
            bars = pd.read_parquet(root / "inputs" / f"{symbol}.parquet")
            features = FeatureFrame(
                symbol,
                signals.open_time,
                signals[[name]],
                signals[[name + "_available"]].rename(columns={name + "_available": name}),
            )
            artifact = Path(result["artifact"])
            assert sha256(artifact) == result["artifact_sha256"]
            evidence = json.loads(artifact.read_text())
            assert (
                feature_digest(features)
                == evidence["protocol"]["input_hashes"]["paper_signal_sha256"]
            )
            assert evidence["protocol"]["execution_policy"] == "paper_state_change_v1"
            per_day = {d: g.reset_index(drop=True) for d, g in bars.groupby("session_date")}
            signal_days = {}
            for day, frame in per_day.items():
                selected = signals.loc[signals.open_time.isin(frame.open_time)].reset_index(
                    drop=True
                )
                assert selected.open_time.tolist() == frame.open_time.tolist()
                if len(selected) == 375 and selected[name + "_available"].all():
                    assert selected[name].isin([0, 1]).all()
                    signal_days[day] = state(selected, name)
            states[(symbol, name)] = signal_days
            frames[symbol] = per_day
            fills = defaultdict(list)
            for fill in evidence["fills"]:
                day = (
                    pd.Timestamp(fill["timestamp"], unit="us", tz="UTC")
                    .tz_convert("Asia/Kolkata")
                    .date()
                    .isoformat()
                )
                fills[day].append(fill)
            assert len(evidence["series"]) == len(evidence["stress_session_returns"])
            for row, stress_return in zip(
                evidence["series"], evidence["stress_session_returns"], strict=True
            ):
                day = row["day"]
                assert day in signal_days
                selected, actual, frame = signal_days[day], fills[day], per_day[day]
                if selected is None:
                    assert not actual and row["n_fills"] == 0
                    assert row["net_return"] == stress_return == 0
                    counts["flat_sessions"] += 1
                    continue
                entry, exit_ = selected
                quantity = Decimal("50000") // Decimal(str(frame.close.iloc[entry]))
                assert len(actual) == row["n_fills"] == 2
                assert [f["side"] for f in actual] == ["BUY", "SELL"]
                assert all(Decimal(f["quantity"]) == quantity for f in actual)
                assert [f["timestamp"] for f in actual] == [
                    int(frame.open_time.iloc[entry + 1]),
                    int(frame.open_time.iloc[exit_ + 1]),
                ]
                buy_open = Decimal(str(frame.open.iloc[entry + 1]))
                sell_open = Decimal(str(frame.open.iloc[exit_ + 1]))
                for multiplier, retained in ((1, row["net_return"]), (2, stress_return)):
                    slip = Decimal(".0005") * multiplier
                    buy, sell = buy_open * (1 + slip), sell_open * (1 - slip)
                    trades = [
                        ChargeTrade(
                            pd.Timestamp(day).date(), symbol, "entry", "BUY", quantity, buy
                        ),
                        ChargeTrade(
                            pd.Timestamp(day).date(), symbol, "exit", "SELL", quantity, sell
                        ),
                    ]
                    fees = estimate_intraday_charges(trades).total * multiplier
                    net = (quantity * (sell - buy) - fees) / Decimal("100000")
                    assert math.isclose(float(net), retained, abs_tol=1e-14)
                    if multiplier == 1:
                        assert Decimal(actual[0]["price"]) == buy
                        assert Decimal(actual[1]["price"]) == sell
                        assert Decimal(row["fees"]) == fees
                counts["active_sessions"] += 1
                counts["base_fills"] += len(actual)
                counts["base_and_stress_session_returns"] += 2
            counts["candidate_sessions"] += len(evidence["series"])
    if training_records is not None:
        prior_result = json.loads((training_records.parent / "results.json").read_text())
        assert sha256(training_records) == prior_result["records_sha256"]
        for row in json.loads(training_records.read_text()):
            if row["symbol"] not in frames or row["multiplier"] != 1:
                continue
            name, day, symbol = row["candidate"], row["day"], row["symbol"]
            assert day <= "2025-12-31"
            expected = (row["signal_slot"], row["exit_signal_slot"]) if row["active"] else None
            assert day in states[(symbol, name)]
            assert states[(symbol, name)][day] == expected
            counts["historical_train_decision_parity_records"] += 1
    write_json(
        output,
        dict(
            version="nse_paper_schedule_verification_v1",
            round_id=round_id,
            summary_sha256=sha256(root / "summary.json"),
            counts=dict(counts),
            fixed_share_quantity_verified=True,
            next_open_timing_verified=True,
            base_and_stress_costs_independently_recomputed=True,
            holding_rebalance_absent=True,
            ranking_source_files_verified=len(feature_protocol["source_files"]),
            causal_history_windows_verified=len(feature_protocol["history_windows"]),
            test_accesses=0,
            promoted=0,
        ),
    )
    print(json.dumps(dict(counts)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("round_id")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--training-records", type=Path)
    args = parser.parse_args()
    verify(args.round_id, args.output, args.training_records)
