"""Frozen longer-horizon TRAIN-only model screen; no VALID, TEST or registry writes.

Three targets and one fixed estimator/calibration protocol. This is conditional
exploratory reused TRAIN research, never a gate-passing or execution claim.
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def save(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, default=str, allow_nan=False)
        stream.write("\n")


def freeze(args):
    from helios.common.lineage import PROJECT_ROOT, git_commit, git_is_dirty

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for source in [
        *sorted((PROJECT_ROOT / "research/helios").rglob("*.py")),
        Path(__file__).resolve(),
        PROJECT_ROOT / "pyproject.toml",
        PROJECT_ROOT / "uv.lock",
    ]:
        relative = source.relative_to(PROJECT_ROOT)
        target = output / "source" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        hashes[str(relative)] = sha(target)
    for relative, expected in hashes.items():
        if sha(PROJECT_ROOT / relative) != expected:
            raise ValueError("source changed while freezing")
    protocol = dict(
        version="nse_longer_horizon_train_screen_v1",
        output=str(output),
        project_root=str(PROJECT_ROOT),
        snapshot=str(args.snapshot.resolve()),
        source_manifest_sha256=sha(args.snapshot.resolve() / "manifest.json"),
        source_commit=git_commit(),
        dirty=git_is_dirty(),
        source_hashes=hashes,
        targets={"m60": 90, "m120": 150, "session_close": 374},
        entry_decision_slot=29,
        entry_opening_slot=30,
        one_entry_per_session=True,
        fit_end="2025-08-31",
        calibration_start="2025-09-01",
        calibration_end="2025-09-30",
        screen_start="2025-10-09",
        train_end="2025-12-31",
        embargo="2025-10-01..2025-10-08",
        model=dict(
            n_estimators=100,
            num_leaves=15,
            min_child_samples=200,
            learning_rate=0.03,
            random_state=42,
            n_jobs=2,
            verbosity=-1,
            deterministic=True,
            force_col_wise=True,
        ),
        calibration="Isotonic expected gross return, September only; never fits screen labels",
        entry_hurdle_bps=21,
        capital_inr=100000,
        target_inr=50000,
        costs="unchanged dated reference estimator, 5bps/side; doubled charges and slip stress",
        criterion=(
            "At least40 dates and20 active stock-days; mean net and all3 months "
            "positive at normal and doubled costs"
        ),
        comparison_count="three fixed aggregate strategies; report all company/target outcomes",
        prior_exposure="Prior TRAIN/VALID exposure; exploratory, no fresh OOS claim",
        source_scope="41 conditional screened historical companies; ex-post cohort, not certified",
        valid_price_reads=False,
        test_access=False,
        formal_registry_results=False,
        promotion=False,
        frozen_gates_changed=False,
    )
    save(output / "protocol.json", protocol)
    script = output / "source" / Path(__file__).resolve().relative_to(PROJECT_ROOT)
    os.execv(
        sys.executable, [sys.executable, str(script), "--frozen", str(output / "protocol.json")]
    )


def run(protocol_path):
    protocol = read(protocol_path)
    output = Path(protocol["output"])
    sys.path.insert(0, str(output / "source/research"))
    import math
    from collections import defaultdict
    from decimal import Decimal

    import numpy as np
    import pandas as pd
    from lightgbm import LGBMRegressor
    from sklearn.isotonic import IsotonicRegression

    from helios.equities.horizon_screen import (
        EXITS,
        FEATURES,
        HURDLE,
        cost_screen,
        forward_return,
        opening_features,
    )
    from helios.equities.paper_features import full_session
    from helios.equities.rebuild import verified_file

    os.chdir("/tmp")
    for relative, expected in protocol["source_hashes"].items():
        if sha(output / "source" / relative) != expected:
            raise ValueError("archived source differs")
    snapshot = Path(protocol["snapshot"])
    if sha(snapshot / "manifest.json") != protocol["source_manifest_sha256"]:
        raise ValueError("snapshot changed after protocol freeze")
    manifest = read(snapshot / "manifest.json")
    if (
        manifest["version"] != "nse_public_minutes_v2"
        or manifest["test_access"]
        or manifest["g7_eligible"]
        or not manifest["complete"]
    ):
        raise ValueError("expected a conditional TEST-sealed source")
    for name, key in (
        ("sessions.json", "sessions_sha256"),
        ("protocol.json", "protocol_sha256"),
        ("universe.json", "universe_sha256"),
        ("session_checks.json", "checks_sha256"),
    ):
        verified_file(snapshot, name, manifest[key])
    records, decoded, exclusions = [], [], []
    for item in sorted(manifest["files"], key=lambda r: r["symbol"]):
        if item["eligible_rows"] <= 0:
            continue
        path = verified_file(snapshot, item["path"], item["sha256"])
        bars = pd.read_parquet(path, filters=[("session_date", "<=", "2025-12-31")])
        if (
            bars.empty
            or set(bars.symbol) != {item["symbol"]}
            or not bars.session_date.between("2025-01-01", "2025-12-31").all()
        ):
            raise ValueError("TRAIN source dates/identity mismatch")
        decoded.append(
            dict(
                symbol=item["symbol"],
                rows=len(bars),
                first_day=bars.session_date.min(),
                last_day=bars.session_date.max(),
                sha256=item["sha256"],
            )
        )
        for day, frame in bars.groupby("session_date", sort=True):
            frame = frame.sort_values("open_time").reset_index(drop=True)
            if not full_session(frame):
                exclusions.append(
                    dict(
                        symbol=item["symbol"], day=day, reason="source_or_full_session_unavailable"
                    )
                )
                continue
            if "2025-10-01" <= day <= "2025-10-08":
                exclusions.append(dict(symbol=item["symbol"], day=day, reason="embargo"))
                continue
            try:
                features = opening_features(frame)
            except ValueError:
                exclusions.append(
                    dict(symbol=item["symbol"], day=day, reason="opening_features_unavailable")
                )
                continue
            row = dict(
                symbol=item["symbol"],
                day=day,
                **features,
                decision_close=float(frame.close.iloc[29]),
                entry_open=float(frame.open.iloc[30]),
                decision_time=int(frame.open_time.iloc[29]) + 60_000_000,
                entry_time=int(frame.open_time.iloc[30]),
            )
            for name, slot in EXITS.items():
                row["target_" + name] = forward_return(frame, slot)
                row["exit_" + name] = float(frame.open.iloc[slot])
                row["label_end_" + name] = int(frame.open_time.iloc[slot]) + 60_000_000
            records.append(row)
        print("Prepared TRAIN prefix " + item["symbol"], flush=True)
    table = pd.DataFrame(records).sort_values(["day", "symbol"]).reset_index(drop=True)
    if table.duplicated(["symbol", "day"]).any():
        raise ValueError("duplicate company/session sample")
    table.to_parquet(output / "train_samples.parquet", index=False)
    save(output / "decoded_scope.json", decoded)
    save(output / "exclusions.json", exclusions)
    fit = table.day <= protocol["fit_end"]
    calibration = table.day.between(protocol["calibration_start"], protocol["calibration_end"])
    screen = table.day.between(protocol["screen_start"], protocol["train_end"])
    if (
        fit.sum() < 500
        or calibration.sum() < 50
        or not (fit.astype(int) + calibration.astype(int) + screen.astype(int) == 1).all()
    ):
        raise ValueError("invalid or overlapping chronological masks")
    outcomes, aggregate, company_outcomes, models = [], [], [], []
    for name in EXITS:
        model = LGBMRegressor(**protocol["model"])
        model.fit(table.loc[fit, list(FEATURES)], table.loc[fit, "target_" + name])
        model_path = output / (name + "_model.txt")
        model.booster_.save_model(str(model_path))
        iso = IsotonicRegression(out_of_bounds="clip")
        raw_cal = model.predict(table.loc[calibration, list(FEATURES)])
        iso.fit(raw_cal, table.loc[calibration, "target_" + name])
        predictions = np.asarray(iso.predict(model.predict(table.loc[screen, list(FEATURES)])))
        save(
            output / (name + "_calibration.json"),
            dict(
                x=iso.X_thresholds_.tolist(),
                y=iso.y_thresholds_.tolist(),
                fit_rows=int(fit.sum()),
                calibration_rows=int(calibration.sum()),
                model_sha256=sha(model_path),
            ),
        )
        models.append(
            dict(
                candidate=name,
                model_sha256=sha(model_path),
                max_screen_expected_bps=float(predictions.max() * 10000),
                entry_hurdle_bps=HURDLE * 10000,
            )
        )
        candidate_rows = []
        for (_, row), prediction in zip(table.loc[screen].iterrows(), predictions, strict=True):
            for multiplier in (1, 2):
                measured = cost_screen(
                    pd.Timestamp(row.day).date(),
                    row.symbol,
                    Decimal(str(row.decision_close)),
                    Decimal(str(row.entry_open)),
                    Decimal(str(row["exit_" + name])),
                    active=bool(prediction > HURDLE),
                    multiplier=multiplier,
                )
                candidate_rows.append(
                    dict(
                        candidate=name,
                        symbol=row.symbol,
                        day=row.day,
                        multiplier=multiplier,
                        expected_gross_return=float(prediction),
                        active=bool(prediction > HURDLE),
                        **measured,
                    )
                )
        outcomes.extend(candidate_rows)
        for symbol in sorted(set(table.symbol)):
            rows = [r for r in candidate_rows if r["symbol"] == symbol]
            scenarios = {}
            for multiplier in (1, 2):
                selected = [r for r in rows if r["multiplier"] == multiplier]
                months = defaultdict(float)
                for r in selected:
                    months[r["day"][:7]] += float(Decimal(r["net"]) / Decimal(100000))
                scenarios[str(multiplier)] = dict(
                    active=sum(r["active"] for r in selected),
                    months=dict(months),
                    net_inr=str(sum((Decimal(r["net"]) for r in selected), Decimal(0))),
                )
            passed = all(
                s["active"] >= 20
                and len(s["months"]) == 3
                and all(v > 0 for v in s["months"].values())
                for s in scenarios.values()
            )
            company_outcomes.append(
                dict(candidate=name, symbol=symbol, scenarios=scenarios, passes_screen=passed)
            )
        scenarios = {}
        for multiplier in (1, 2):
            by_day = defaultdict(list)
            for row in candidate_rows:
                if row["multiplier"] == multiplier:
                    by_day[row["day"]].append(float(Decimal(row["net"]) / Decimal(100000)))
            daily = {d: float(np.mean(values)) for d, values in sorted(by_day.items())}
            values = np.asarray(list(daily.values()))
            months = defaultdict(float)
            for day, value in daily.items():
                months[day[:7]] += value
            scenarios[str(multiplier)] = dict(
                dates=len(daily),
                active=sum(r["active"] for r in candidate_rows if r["multiplier"] == multiplier),
                mean_stock_day_net_bps=float(
                    np.mean(
                        [
                            float(Decimal(r["net"]) / Decimal(100000)) * 10000
                            for r in candidate_rows
                            if r["multiplier"] == multiplier
                        ]
                    )
                ),
                daily_mean_account_returns=daily,
                months=dict(months),
                diagnostic_sharpe=None
                if np.std(values, ddof=1) == 0
                else float(np.mean(values) / np.std(values, ddof=1) * math.sqrt(252)),
            )
        passed = all(
            s["dates"] >= 40
            and s["active"] >= 20
            and s["mean_stock_day_net_bps"] > 0
            and len(s["months"]) == 3
            and all(v > 0 for v in s["months"].values())
            for s in scenarios.values()
        )
        aggregate.append(dict(candidate=name, scenarios=scenarios, passes_screen=passed))
        print(
            f"SCREEN {name}: {passed}; max expected {predictions.max() * 10000:.4f}bps", flush=True
        )
    save(output / "session_records.json", outcomes)
    save(
        output / "results.json",
        dict(
            version=protocol["version"],
            protocol_sha256=sha(protocol_path),
            sample_sha256=sha(output / "train_samples.parquet"),
            records_sha256=sha(output / "session_records.json"),
            fit_rows=int(fit.sum()),
            calibration_rows=int(calibration.sum()),
            screen_rows=int(screen.sum()),
            models=models,
            aggregate=aggregate,
            companies=company_outcomes,
            aggregate_survivors=sum(r["passes_screen"] for r in aggregate),
            company_survivors=sum(r["passes_screen"] for r in company_outcomes),
            source_certified=False,
            official_gate_evaluation=False,
            formal_registry_results=0,
            valid_price_reads=0,
            test_accesses=0,
            promoted=0,
        ),
    )
    print("COMPLETED all three fixed TRAIN-only models", flush=True)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--frozen":
        run(Path(sys.argv[2]))
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--snapshot", type=Path, required=True)
        parser.add_argument("--output", type=Path, required=True)
        freeze(parser.parse_args())
