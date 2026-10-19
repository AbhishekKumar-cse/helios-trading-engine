"""Independently reconcile a completed zero-entry TRAIN horizon screen.

This bounded verifier refuses active-trade rounds, which require a fill audit.
It never fits on the screen period or loads VALID/TEST candles.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from lightgbm import Booster
from sklearn.isotonic import IsotonicRegression


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def verify(root):
    protocol = read(root / "protocol.json")
    result = read(root / "results.json")
    assert result["protocol_sha256"] == sha(root / "protocol.json")
    assert result["sample_sha256"] == sha(root / "train_samples.parquet")
    assert result["records_sha256"] == sha(root / "session_records.json")
    assert protocol["version"] == "nse_longer_horizon_train_screen_v1"
    assert protocol["entry_hurdle_bps"] == 21
    assert protocol["targets"] == {"m60": 90, "m120": 150, "session_close": 374}
    assert not protocol["test_access"] and not protocol["valid_price_reads"]
    for relative, expected in protocol["source_hashes"].items():
        assert sha(root / "source" / relative) == expected
    snapshot = Path(protocol["snapshot"])
    assert sha(snapshot / "manifest.json") == protocol["source_manifest_sha256"]
    manifest = read(snapshot / "manifest.json")
    table = pd.read_parquet(root / "train_samples.parquet")
    assert table.day.between("2025-01-01", "2025-12-31").all()
    assert not table.duplicated(["symbol", "day"]).any()
    fit = table.day <= "2025-08-31"
    cal = table.day.between("2025-09-01", "2025-09-30")
    screen = table.day.between("2025-10-09", "2025-12-31")
    assert (fit.astype(int) + cal.astype(int) + screen.astype(int) == 1).all()
    for key, mask in (("fit_rows", fit), ("calibration_rows", cal), ("screen_rows", screen)):
        assert result[key] == int(mask.sum())
    assert (table.decision_time == table.entry_time).all()
    features = [
        "move_5",
        "move_15",
        "move_30",
        "recent_5",
        "recent_15",
        "range_30",
        "location_30",
        "volatility_30",
        "volume_ratio",
        "up_fraction",
    ]
    # First retained TRAIN session for every company, directly against source.
    # Every source file is hashed; only these selected TRAIN sessions are decoded.
    checked = 0
    for item in manifest["files"]:
        if item["eligible_rows"] <= 0:
            continue
        path = snapshot / item["path"]
        assert sha(path) == item["sha256"]
        row = table.loc[table.symbol == item["symbol"]].iloc[0]
        bars = pd.read_parquet(path, filters=[("session_date", "==", row.day)])
        bars = bars.sort_values("open_time").reset_index(drop=True)
        assert len(bars) == 375
        assert (bars.open_time.diff().iloc[1:] == 60_000_000).all()
        part = bars.iloc[:30]
        opening = float(part.open.iloc[0])
        closes = part.close.to_numpy(dtype=float)
        high, low = float(part.high.max()), float(part.low.min())
        expected = [
            closes[4] / opening - 1,
            closes[14] / opening - 1,
            closes[29] / opening - 1,
            closes[29] / closes[24] - 1,
            closes[29] / closes[14] - 1,
            (high - low) / opening,
            (closes[29] - low) / (high - low),
            np.std(np.diff(np.log(closes))),
            float(part.volume.iloc[-5:].mean()) / float(part.volume.iloc[:5].mean()),
            np.mean(np.diff(closes) > 0),
        ]
        np.testing.assert_allclose(row[features].to_numpy(dtype=float), expected, atol=1e-14)
        assert row.decision_close == float(part.close.iloc[-1])
        assert row.entry_open == float(bars.open.iloc[30])
        for candidate, slot in protocol["targets"].items():
            assert row["exit_" + candidate] == float(bars.open.iloc[slot])
        checked += 1
    records = pd.DataFrame(read(root / "session_records.json"))
    assert len(records) == int(screen.sum()) * 6
    assert not records.duplicated(["candidate", "symbol", "day", "multiplier"]).any()
    for candidate, slot in protocol["targets"].items():
        np.testing.assert_allclose(
            table["target_" + candidate],
            table["exit_" + candidate] / table.entry_open - 1,
            atol=1e-14,
        )
        assert (
            table["label_end_" + candidate] == table.entry_time + (slot - 29) * 60_000_000
        ).all()
        model_info = next(r for r in result["models"] if r["candidate"] == candidate)
        assert sha(root / (candidate + "_model.txt")) == model_info["model_sha256"]
        model = Booster(model_file=str(root / (candidate + "_model.txt")))
        assert model.feature_name() == features
        calibration = read(root / (candidate + "_calibration.json"))
        assert calibration["model_sha256"] == model_info["model_sha256"]
        iso = IsotonicRegression(out_of_bounds="clip")
        iso.fit(model.predict(table.loc[cal, features]), table.loc[cal, "target_" + candidate])
        np.testing.assert_array_equal(iso.X_thresholds_, calibration["x"])
        np.testing.assert_array_equal(iso.y_thresholds_, calibration["y"])
        predictions = iso.predict(model.predict(table.loc[screen, features]))
        np.testing.assert_allclose(predictions.max() * 10000, model_info["max_screen_expected_bps"])
        assert not (predictions > 0.0021).any(), "Active trades require a separate fill audit"
        for multiplier in (1, 2):
            rows = records.loc[
                (records.candidate == candidate) & (records.multiplier == multiplier)
            ]
            expected_keys = list(
                zip(table.loc[screen, "symbol"], table.loc[screen, "day"], strict=True)
            )
            assert list(zip(rows.symbol, rows.day, strict=True)) == expected_keys
            np.testing.assert_allclose(rows.expected_gross_return, predictions, atol=1e-14)
            assert not rows.active.any()
            assert (rows[["quantity", "gross", "slippage", "fees", "net"]] == "0").all().all()
        summary = next(r for r in result["aggregate"] if r["candidate"] == candidate)
        assert not summary["passes_screen"]
        for values in summary["scenarios"].values():
            assert values["dates"] == table.loc[screen, "day"].nunique()
            assert values["active"] == values["mean_stock_day_net_bps"] == 0
            assert values["diagnostic_sharpe"] is None
            assert set(values["daily_mean_account_returns"]) == set(table.loc[screen, "day"])
            assert set(values["daily_mean_account_returns"].values()) == {0}
            assert values["months"] == {"2025-10": 0, "2025-11": 0, "2025-12": 0}
    assert len(result["companies"]) == table.symbol.nunique() * 3
    for company in result["companies"]:
        assert not company["passes_screen"]
        expected_months = set(
            table.loc[screen & (table.symbol == company["symbol"]), "day"].str[:7]
        )
        for values in company["scenarios"].values():
            assert values["active"] == 0 and values["net_inr"] == "0"
            assert values["months"] == dict.fromkeys(expected_months, 0)
    for key in (
        "aggregate_survivors",
        "company_survivors",
        "formal_registry_results",
        "valid_price_reads",
        "test_accesses",
        "promoted",
    ):
        assert result[key] == 0
    assert not result["source_certified"] and not result["official_gate_evaluation"]
    receipt = dict(
        passed=True,
        source_samples=checked,
        companies=int(table.symbol.nunique()),
        train_rows=len(table),
        screen_rows=int(screen.sum()),
        session_scenario_records=len(records),
        result_sha256=sha(root / "results.json"),
        verifier_sha256=sha(Path(__file__)),
        all_source_hashes_verified=True,
        calibration_refit_matches=True,
        all_screen_predictions_reproduced=True,
        all_outcomes_observed_flat=True,
        active_trades=0,
        valid_price_reads=0,
        test_accesses=0,
        scope="Zero-entry TRAIN screen audit; no model refit, certification or gate approval",
    )
    with (root / "verification.json").open("x") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    verify(parser.parse_args().root.resolve())
