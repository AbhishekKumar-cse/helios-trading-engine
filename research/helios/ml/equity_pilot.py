"""Fixed daily/hourly equity ML development baselines; TEST is inaccessible.

Run after helios.data.equities. This does not promote a tradable alpha or alter
the existing crypto registry. Outputs are immutable, local development evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import shutil
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier, early_stopping
from sklearn.metrics import accuracy_score, f1_score, log_loss, roc_auc_score

from helios.common.config import config_hash, load_config
from helios.common.lineage import PROJECT_ROOT, RunContext
from helios.data.equities import EquityPilotConfig, constituents, sha256, write_json

ModelInterval = Literal["1d", "60m"]
FEATURES = (
    "return_1",
    "return_5",
    "return_20",
    "volatility_20",
    "body",
    "range",
    "close_location",
    "relative_volume_20",
    "open_gap",
    "bar_slot",
)


HOURLY_FEATURES = (
    "return_1",
    "return_2",
    "return_3",
    "volatility_3",
    "body",
    "range",
    "close_location",
    "relative_volume_3",
    "open_gap",
    "bar_slot",
)


def features_for(interval: ModelInterval) -> tuple[str, ...]:
    return FEATURES if interval == "1d" else HOURLY_FEATURES


def window(config: EquityPilotConfig, interval: ModelInterval) -> tuple[str, str, str, str]:
    prefix = "daily" if interval == "1d" else "hourly"
    values = [
        getattr(config, f"{prefix}_{key}").isoformat()
        for key in ("start", "train_end", "valid_start", "valid_end")
    ]
    return values[0], values[1], values[2], values[3]


def load_inputs(
    snapshot: Path, config: EquityPilotConfig, interval: ModelInterval
) -> tuple[list[pd.DataFrame], dict[str, Any], str]:
    manifest_path = snapshot / "manifest.json"
    manifest: dict[str, Any] = json.loads(manifest_path.read_text())
    if manifest["config_hash"] != config_hash(config):
        raise ValueError("snapshot was collected under a different protocol")
    if sha256(snapshot / "protocol.json") != manifest["protocol_sha256"]:
        raise ValueError("snapshot protocol hash mismatch")
    if sha256(snapshot / "constituents.csv") != manifest["universe_sha256"]:
        raise ValueError("constituent snapshot hash mismatch")
    members = constituents((snapshot / "constituents.csv").read_bytes())
    expected = {member["Symbol"] for member in members}
    records = [record for record in manifest["files"] if record["interval"] == interval]
    if len(records) != 50 or {record["symbol"] for record in records} != expected:
        raise ValueError(f"{interval} requires all 50 distinct constituents; no silent subset")
    _, _, _, valid_end = window(config, interval)
    frames = []
    for record in records:
        path, raw = snapshot / record["path"], snapshot / record["raw_path"]
        for candidate in (path, raw):
            if not candidate.resolve().is_relative_to(snapshot.resolve()):
                raise ValueError("input path escapes the snapshot")
        if sha256(path) != record["sha256"] or sha256(raw) != record["raw_sha256"]:
            raise ValueError("equity input fingerprint mismatch")
        # Push the boundary predicate into the reader. TEST observations never enter features.
        frame = pd.read_parquet(path, filters=[("session_date", "<=", valid_end)])
        if frame.empty or set(frame["symbol"]) != {record["symbol"]}:
            raise ValueError("missing development observations or mismatched symbol")
        if not (frame["session_date"] <= valid_end).all():
            raise ValueError("TEST boundary violation")
        frames.append(frame)
    return frames, manifest, sha256(manifest_path)


def features_and_labels(
    frame: pd.DataFrame, interval: ModelInterval, *, include_unlabelled: bool = False
) -> pd.DataFrame:
    """Causal per-symbol features; horizon is next bar open-to-close.

    Daily uses the next observed session (at most seven calendar days later).
    Hourly only labels an immediately adjacent full hour within the same session.
    No feature/label ever crosses symbols. Gaps reset the lookback rather than fill it.
    """
    if frame.empty or frame["symbol"].nunique() != 1:
        raise ValueError("features require exactly one nonempty symbol")
    frame = frame.sort_values("timestamp").copy().reset_index(drop=True)
    if frame["timestamp"].duplicated().any():
        raise ValueError("duplicate bar timestamp")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame["available_at"] = pd.to_datetime(frame["available_at"], utc=True)
    if not (frame["available_at"] > frame["timestamp"]).all():
        raise ValueError("bars must become available after opening")
    # The scheduled final 15 minutes are not a full hour; do not include them in
    # the full-hour sequence. The next session can still use prior complete hours.
    if interval == "60m":
        frame = frame.loc[frame["full_bar"]].copy().reset_index(drop=True)
    good = frame["full_bar"] & (frame["volume"] > 0)
    previous_time = frame["timestamp"].shift(1)
    same_session = frame["session_date"] == frame["session_date"].shift(1)
    gap = frame["timestamp"] - previous_time
    if interval == "1d":
        broken = gap > pd.Timedelta(days=7)
    else:
        local = frame["timestamp"].dt.tz_convert("Asia/Kolkata")
        first_hour = (local.dt.hour == 9) & (local.dt.minute == 15)
        broken = (
            (same_session & (gap != pd.Timedelta(hours=1)))
            | (~same_session & ~first_hour)
            | (gap > pd.Timedelta(days=7))
        )
    segments = (broken | ~good | ~good.shift(1, fill_value=False)).cumsum()
    price = frame["adjusted_close"] if interval == "1d" else frame["close"]
    grouped_price = price.groupby(segments)
    returns = price / grouped_price.shift(1) - 1
    frame["return_1"] = returns
    medium, long = (5, 20) if interval == "1d" else (2, 3)
    frame[f"return_{medium}"] = price / grouped_price.shift(medium) - 1
    frame[f"return_{long}"] = price / grouped_price.shift(long) - 1
    frame[f"volatility_{long}"] = returns.groupby(segments).transform(
        lambda values: values.rolling(long, min_periods=long).std(ddof=0)
    )
    frame["body"] = frame["close"] / frame["open"] - 1
    frame["range"] = (frame["high"] - frame["low"]) / frame["open"]
    span = (frame["high"] - frame["low"]).replace(0, np.nan)
    frame["close_location"] = (frame["close"] - frame["low"]) / span
    rolling_volume = (
        frame["volume"]
        .groupby(segments)
        .transform(lambda values: values.rolling(long, min_periods=long).mean())
    )
    frame[f"relative_volume_{long}"] = frame["volume"] / rolling_volume
    factor = price / frame["close"]
    frame["open_gap"] = frame["open"] * factor / grouped_price.shift(1) - 1
    local = frame["timestamp"].dt.tz_convert("Asia/Kolkata")
    frame["bar_slot"] = 0 if interval == "1d" else (local.dt.hour * 60 + local.dt.minute - 555) / 60
    frame["label_open_time"] = frame["timestamp"].shift(-1)
    frame["label_end_time"] = frame["available_at"].shift(-1)
    frame["label_session"] = frame["session_date"].shift(-1)
    frame["target"] = (frame["close"] / frame["open"] - 1).shift(-1)
    eligible = good & good.shift(-1, fill_value=False)
    eligible &= frame["available_at"] <= frame["label_open_time"]
    if interval == "60m":
        eligible &= frame["session_date"] == frame["label_session"]
        eligible &= frame["label_open_time"] - frame["timestamp"] == pd.Timedelta(hours=1)
    else:
        eligible &= frame["label_open_time"] - frame["timestamp"] <= pd.Timedelta(days=7)
    if include_unlabelled:
        frame["feature_available"] = good & np.isfinite(
            frame[list(features_for(interval))].to_numpy(dtype=float)
        ).all(axis=1)
        return frame.reset_index(drop=True)
    finite = np.isfinite(frame[[*features_for(interval), "target"]].to_numpy(dtype=float)).all(
        axis=1
    )
    return frame.loc[eligible & finite].reset_index(drop=True)


def split_samples(
    frames: list[pd.DataFrame], config: EquityPilotConfig, interval: ModelInterval
) -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, object]]]:
    start, train_end, valid_start, valid_end = window(config, interval)
    train_parts, valid_parts, coverage = [], [], []
    for frame in frames:
        # Defensive boundary for callers other than the guarded Parquet reader.
        frame = frame.loc[frame["session_date"] <= valid_end].copy()
        samples = features_and_labels(frame, interval)
        train = samples.loc[
            (samples["session_date"] >= start)
            & (samples["session_date"] <= train_end)
            & (samples["label_session"] <= train_end)
        ]
        valid = samples.loc[
            (samples["session_date"] >= valid_start)
            & (samples["session_date"] <= valid_end)
            & (samples["label_session"] <= valid_end)
        ]
        coverage.append(
            dict(
                symbol=str(frame["symbol"].iloc[0]),
                development_bars=len(frame),
                usable_samples=len(samples),
                train_samples=len(train),
                valid_samples=len(valid),
                first_session=str(frame["session_date"].min()),
                excluded_from_fit="fewer than 100 TRAIN or 20 VALID samples"
                if len(train) < 100 or len(valid) < 20
                else None,
            )
        )
        if len(train) >= 100 and len(valid) >= 20:
            train_parts.append(train)
            valid_parts.append(valid)
    if not train_parts or not valid_parts:
        raise ValueError("not enough equity history for training and validation")
    train = pd.concat(train_parts).sort_values(["timestamp", "symbol"]).reset_index(drop=True)
    valid = pd.concat(valid_parts).sort_values(["timestamp", "symbol"]).reset_index(drop=True)
    if train["label_end_time"].max() >= valid["timestamp"].min():
        raise ValueError("TRAIN labels overlap VALID")
    return train, valid, coverage


def metrics(labels: np.ndarray[Any, Any], probability: np.ndarray[Any, Any]) -> dict[str, Any]:
    predicted = (probability >= 0.5).astype(int)
    return dict(
        accuracy=float(accuracy_score(labels, predicted)),
        macro_f1=float(f1_score(labels, predicted, average="macro", zero_division=0)),
        log_loss=float(log_loss(labels, probability, labels=[0, 1])),
        roc_auc=float(roc_auc_score(labels, probability)) if len(np.unique(labels)) == 2 else None,
    )


def sample_hash(frame: pd.DataFrame, interval: ModelInterval) -> str:
    return hashlib.sha256(
        frame[["symbol", "timestamp", "label_end_time", *features_for(interval), "target"]]
        .to_csv(index=False, float_format="%.17g")
        .encode()
    ).hexdigest()


def fit(snapshot: Path, config: EquityPilotConfig, root: Path) -> Path:
    run = root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8])
    run.mkdir(parents=True, exist_ok=False)
    (run / "source").mkdir()
    sources = [
        Path(__file__),
        PROJECT_ROOT / "research/helios/data/equities.py",
        PROJECT_ROOT / "research/helios/common/config.py",
        PROJECT_ROOT / "research/helios/common/lineage.py",
        PROJECT_ROOT / "pyproject.toml",
        PROJECT_ROOT / "uv.lock",
    ]
    source_hashes = {}
    for path in sources:
        target = run / "source" / path.name
        shutil.copyfile(path, target)
        source_hashes[str(path.relative_to(PROJECT_ROOT))] = sha256(target)
    write_json(run / "protocol.json", config.model_dump(mode="json"))
    write_json(
        run / "feature_protocol.json",
        dict(
            version="equity_causal_features_v2",
            daily=list(FEATURES),
            hourly=list(HOURLY_FEATURES),
            hourly_change_reason=(
                "Initial 20-bar hourly lookback failed eligibility due to systematic opening "
                "zero-volume bars. Freeze 1/2/3-bar windows before the first hourly model fit; "
                "retain strict zero-volume/gap exclusion. No hourly metrics informed this change."
            ),
        ),
    )
    # Write the protocol/source evidence before fitting any model or viewing a metric.
    summary: dict[str, Any] = dict(
        status="DEVELOPMENT_ONLY",
        created_at=datetime.now(UTC).isoformat(),
        snapshot=str(snapshot),
        config_hash=config_hash(config),
        source_sha256=source_hashes,
        feature_protocol_sha256=sha256(run / "feature_protocol.json"),
        features={"1d": list(FEATURES), "60m": list(HOURLY_FEATURES)},
        label="next_bar_open_to_close_direction_v1",
        test_observation_accesses=0,
        registry_writes=0,
        is_simulated=True,
        versions={
            name: importlib.metadata.version(name)
            for name in ("lightgbm", "numpy", "pandas", "scikit-learn", "pyarrow")
        },
        python=platform.python_version(),
        limitations=[
            "Current-universe survivorship bias; not a point-in-time Nifty index backtest.",
            "Yahoo-distributed data and adjustments are not exchange-verified or point-in-time.",
            "VALID selects early stopping; metrics are development evidence, not a final test.",
            "No fees, taxes, slippage, executable P&L, promotion or live orders.",
            "Daily uses observed sessions, not an independently verified historical calendar.",
            "Full hourly bars only; labels never cross missing hours or overnight boundaries.",
            "Recent minute coverage is ingestion evidence only; no minute model is fitted.",
            "Uncommitted development source is archived; this is not a clean reported run.",
        ],
        models={},
    )
    for interval in ("1d", "60m"):
        frames, manifest, snapshot_hash = load_inputs(snapshot, config, interval)
        context = RunContext.capture(config, snapshot_hash, config.seed, reported=False)
        train, valid, coverage = split_samples(frames, config, interval)
        names = features_for(interval)
        x_train, x_valid = train[list(names)], valid[list(names)]
        y_train = (train["target"].to_numpy() > 0).astype(int)
        y_valid = (valid["target"].to_numpy() > 0).astype(int)
        if len(np.unique(y_train)) != 2:
            raise ValueError("TRAIN must contain both direction classes")
        model = LGBMClassifier(
            objective="binary",
            metric="binary_logloss",
            n_estimators=config.n_estimators,
            num_leaves=config.num_leaves,
            min_child_samples=config.min_child_samples,
            learning_rate=config.learning_rate,
            reg_lambda=1.0,
            random_state=config.seed,
            n_jobs=2,
            verbosity=-1,
            deterministic=True,
            force_col_wise=True,
            data_random_seed=config.seed,
            feature_fraction_seed=config.seed,
            bagging_seed=config.seed,
        )
        model.fit(
            x_train,
            y_train,
            eval_X=x_valid,
            eval_y=y_valid,
            eval_metric="binary_logloss",
            callbacks=[
                early_stopping(config.stopping_rounds, first_metric_only=True, verbose=False)
            ],
        )
        probability = np.asarray(model.predict_proba(x_valid), dtype=float)[:, 1]
        baseline = np.full(len(y_valid), float(y_train.mean()))
        model_path = run / f"lightgbm_{interval}.txt"
        model.booster_.save_model(str(model_path))
        predictions = valid[
            ["symbol", "timestamp", "label_open_time", "label_end_time", "target"]
        ].copy()
        predictions["probability_up"] = probability
        prediction_path = run / f"valid_predictions_{interval}.parquet"
        predictions.to_parquet(prediction_path, index=False)
        evaluated = metrics(y_valid, probability)
        by_symbol = [
            dict(
                symbol=symbol,
                n_samples=len(part),
                **metrics(
                    (part["target"].to_numpy() > 0).astype(int), part["probability_up"].to_numpy()
                ),
            )
            for symbol, part in predictions.groupby("symbol", sort=True)
        ]
        result = dict(
            interval=interval,
            lineage=asdict(context),
            manifest_sha256=snapshot_hash,
            train_samples=len(train),
            valid_samples=len(valid),
            train_symbols=int(train["symbol"].nunique()),
            valid_symbols=int(valid["symbol"].nunique()),
            train_sample_sha256=sample_hash(train, interval),
            valid_sample_sha256=sample_hash(valid, interval),
            best_iteration=int(model.best_iteration_),
            model_metrics=evaluated,
            train_constant_baseline=metrics(y_valid, baseline),
            train_positive_fraction=float(y_train.mean()),
            coverage=coverage,
            by_symbol=by_symbol,
            model_sha256=sha256(model_path),
            predictions_sha256=sha256(prediction_path),
            feature_importance=dict(zip(names, model.feature_importances_.tolist(), strict=True)),
            snapshot_files=[
                dict(
                    symbol=record["symbol"],
                    sha256=record["sha256"],
                    raw_sha256=record["raw_sha256"],
                )
                for record in manifest["files"]
                if record["interval"] == interval
            ],
        )
        write_json(run / f"result_{interval}.json", result)
        summary["models"][interval] = result
        print(f"{interval}: TRAIN {len(train)}, VALID {len(valid)}, {evaluated}", flush=True)
    write_json(run / "report.json", summary)
    print(f"Run: {run}", flush=True)
    return run


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--config", type=Path, default=Path("configs/equities/nifty50_pilot.yaml"))
    parser.add_argument("--root", type=Path, default=Path("reports_out/equities"))
    args = parser.parse_args()
    fit(args.snapshot, load_config(args.config, EquityPilotConfig), args.root)


if __name__ == "__main__":
    main()
