"""TRAIN-only classifier and disjoint TRAIN-tail expected-return calibration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from lightgbm import Booster, LGBMClassifier
from sklearn.isotonic import IsotonicRegression

from helios.alpha.evaluator import AlphaSeries
from helios.alpha.output import BoundedAlphaSeries, bound_alpha
from helios.data.equities import sha256, write_json
from helios.equities.config import EquityResearchPolicy
from helios.equities.features import minute_samples
from helios.equities.inputs import EquityInputs
from helios.features.runner import FeatureFrame
from helios.ml.equity_pilot import features_and_labels, features_for, sample_hash

FIT_END = "2025-09-30"
CAL_START = "2025-10-09"
MODEL_PROTOCOL = dict(
    version="nse_train_only_ml_v1",
    fit_end=FIT_END,
    calibration_start=CAL_START,
    calibration_end="2025-12-31",
    label="next_full_hour_open_to_close_return",
    n_estimators=100,
    num_leaves=15,
    min_child_samples=200,
    learning_rate=0.03,
    calibration="isotonic expected return on disjoint TRAIN tail; no VALID selection",
)


def model_protocol(policy: EquityResearchPolicy) -> dict[str, Any]:
    if policy.interval == "1h":
        return MODEL_PROTOCOL.copy()
    return MODEL_PROTOCOL | dict(
        version="nse_minute_train_only_ml_v1",
        label="next_minute_open_to_close_return",
        sample_rule="fixed UTC opening minute divisible by 5; TRAIN/calibration only",
    )


@dataclass(frozen=True)
class EquityModel:
    booster: Booster
    thresholds: tuple[float, ...]
    returns: tuple[float, ...]
    available_after: int
    model_hash: str
    calibration_hash: str
    path: Path

    def alpha(self, frame: FeatureFrame, policy: EquityResearchPolicy) -> BoundedAlphaSeries:
        mask = frame.available.all(axis=1) & (frame.open_time >= self.available_after)
        values = np.full(frame.rows, np.nan)
        if mask.any():
            probabilities = np.asarray(self.booster.predict(frame.values.loc[mask]), dtype=float)
            expected = np.interp(probabilities, self.thresholds, self.returns)
            round_trip = 2 * (policy.commission_tax_proxy_bps + policy.slippage_proxy_bps) / 10000
            # Expected payoff is calibrated using TRAIN only; net edge must clear both sides.
            scale = max(round_trip, 0.0001)
            values[mask.to_numpy()] = np.clip((expected - round_trip) / scale, 0, 1)
        return bound_alpha(
            AlphaSeries(frame.symbol, frame.open_time.copy(), pd.Series(values), mask.copy())
        )


def fit_equity_model(
    inputs: list[EquityInputs], policy: EquityResearchPolicy, output: Path
) -> tuple[EquityModel, dict[str, Any]]:
    """Protocol must be preregistered by the caller before this function runs."""
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "protocol.json", model_protocol(policy) | {"seed": policy.seed})
    train_parts, calibration_parts = [], []
    for source in inputs:
        history = source.bars.loc[source.bars.session_date <= policy.train_end.isoformat()]
        samples = (
            features_and_labels(history, "60m")
            if policy.interval == "1h"
            else minute_samples(history)
        )
        if policy.interval == "1m":
            samples = samples.loc[(samples.timestamp.dt.minute % 5) == 0].copy()
            samples = samples[
                [
                    "symbol",
                    "timestamp",
                    "session_date",
                    "label_session",
                    "label_end_time",
                    "target",
                    *features_for("60m"),
                ]
            ]
        train_parts.append(samples.loc[samples.label_session <= FIT_END])
        calibration_parts.append(
            samples.loc[
                (samples.session_date >= CAL_START)
                & (samples.label_session <= policy.train_end.isoformat())
            ]
        )
    train = pd.concat(train_parts).sort_values(["timestamp", "symbol"]).reset_index(drop=True)
    calibration = (
        pd.concat(calibration_parts).sort_values(["timestamp", "symbol"]).reset_index(drop=True)
    )
    if (
        len(train) < 1000
        or len(calibration) < 100
        or train.label_end_time.max() >= calibration.timestamp.min()
    ):
        raise ValueError("ML needs disjoint chronological TRAIN fit/calibration samples")
    names = list(features_for("60m"))
    y_train = (train.target.to_numpy() > 0).astype(int)
    if len(np.unique(y_train)) != 2:
        raise ValueError("TRAIN classifier requires both classes")
    model = LGBMClassifier(
        objective="binary",
        n_estimators=100,
        num_leaves=15,
        min_child_samples=200,
        learning_rate=0.03,
        reg_lambda=1.0,
        random_state=policy.seed,
        n_jobs=2,
        verbosity=-1,
        deterministic=True,
        force_col_wise=True,
        data_random_seed=policy.seed,
        feature_fraction_seed=policy.seed,
        bagging_seed=policy.seed,
    )
    model.fit(train[names], y_train)
    probability = np.asarray(model.predict_proba(calibration[names]), dtype=float)[:, 1]
    mapping = IsotonicRegression(out_of_bounds="clip").fit(
        probability, calibration.target.to_numpy()
    )
    model_path = output / "model.txt"
    model.booster_.save_model(str(model_path))
    available = int(
        pd.Timestamp(policy.train_end.isoformat(), tz="Asia/Kolkata").value // 1000 + 86_400_000_000
    )
    payload: dict[str, Any] = dict(
        version="nse_expected_return_isotonic_v1",
        model_sha256=sha256(model_path),
        x=[float(value) for value in mapping.X_thresholds_],
        y=[float(value) for value in mapping.y_thresholds_],
        available_after_us=available,
        train_samples=len(train),
        calibration_samples=len(calibration),
        train_sample_sha256=sample_hash(train, "60m"),
        calibration_sample_sha256=sample_hash(calibration, "60m"),
        train_last_label=str(train.label_end_time.max()),
        calibration_first_feature=str(calibration.timestamp.min()),
        calibration_last_label=str(calibration.label_end_time.max()),
        valid_observations_used_for_fit_or_calibration=False,
        test_access=False,
    )
    write_json(output / "calibration.json", payload)
    frozen = EquityModel(
        Booster(model_file=str(model_path)),
        tuple(payload["x"]),
        tuple(payload["y"]),
        available,
        sha256(model_path),
        sha256(output / "calibration.json"),
        output,
    )
    reloaded = np.asarray(frozen.booster.predict(calibration[names]), dtype=float)
    np.testing.assert_allclose(reloaded, probability, rtol=0, atol=1e-12)
    return frozen, payload
