"""Calibrated expected edge minus explicit cost, causal scaling and bounds (137)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

import numpy as np
import pandas as pd
from pydantic import Field, StrictInt, model_validator

from helios.common.config import HeliosConfig, config_hash
from helios.common.project_config import FeesConfig
from helios.common.types import AlphaStatus, AlphaValue, DecisionLineage
from helios.features.helpers import zscore
from helios.ml.calibration import IsotonicMap
from helios.ml.dataset import HOUR_US, DatasetError
from helios.ml.splits import SplitDataset, dataset_for_split
from helios.registry.results import Split


class TrainingPayoffs(HeliosConfig):
    means_bps: dict[str, tuple[float, float]]  # mean positive return, mean nonpositive return
    counts: dict[str, tuple[int, int]]
    snapshot_id: str
    available_after_us: int = Field(ge=0)

    @model_validator(mode="after")
    def _means(self) -> Self:
        if not self.means_bps or set(self.counts) != set(self.means_bps):
            raise ValueError("payoff universe/count mismatch")
        for symbol, (up, down) in self.means_bps.items():
            if not np.isfinite([up, down]).all() or up <= 0 or down > 0:
                raise ValueError("payoffs require finite positive/nonpositive class means")
            if min(self.counts[symbol]) < 1:
                raise ValueError("each payoff class requires TRAIN observations")
        return self


def fit_train_payoffs(train: SplitDataset) -> TrainingPayoffs:
    if train.window.split is not Split.TRAIN:
        raise DatasetError("return magnitude fitting requires TRAIN only")
    if (
        train.dataset.snapshot_id is None
        or dataset_for_split(train.dataset, train.window).dataset.samples != train.dataset.samples
    ):
        raise DatasetError("TRAIN payoff samples cross split boundaries or lack snapshot")
    samples = train.dataset.samples
    means, counts = {}, {}
    for symbol in sorted({s.symbol for s in samples}):
        returns = np.array([s.target for s in samples if s.symbol == symbol]) * 10_000
        positive = returns > 0
        if not np.isfinite(returns).all() or positive.all() or not positive.any():
            raise DatasetError("TRAIN payoffs require finite returns in both classes")
        means[symbol] = (float(returns[positive].mean()), float(returns[~positive].mean()))
        counts[symbol] = (int(positive.sum()), int((~positive).sum()))
    return TrainingPayoffs(
        means_bps=means,
        counts=counts,
        snapshot_id=train.dataset.snapshot_id,
        available_after_us=train.window.end_us,
    )


class MLAlphaPolicy(HeliosConfig):
    calibration: IsotonicMap
    payoffs: TrainingPayoffs
    fees: FeesConfig
    window: StrictInt = Field(default=168, ge=2)
    # One complete entry+exit at accepted per-side taker/slippage assumptions.
    cost_sides: StrictInt = Field(default=2, ge=1, le=2)

    @model_validator(mode="after")
    def _snapshot(self) -> Self:
        if self.calibration.snapshot_id != self.payoffs.snapshot_id:
            raise ValueError("calibration and TRAIN payoffs must share a snapshot")
        if not set(self.payoffs.means_bps).issubset(self.fees.slippage_bps):
            raise ValueError("every payoff symbol requires explicit costs")
        return self


@dataclass(frozen=True)
class MLAlphaSeries:
    values: tuple[AlphaValue, ...]
    diagnostics: pd.DataFrame
    policy_hash: str


def prediction_to_alpha(
    predictions: pd.DataFrame, policy: MLAlphaPolicy, lineage: DecisionLineage
) -> MLAlphaSeries:
    policy = MLAlphaPolicy.model_validate(policy.model_dump())
    if (
        lineage.config_hash != config_hash(policy)
        or lineage.snapshot_id != policy.calibration.snapshot_id
        or lineage.model_hash != policy.calibration.model_sha256
    ):
        raise DatasetError("ML alpha requires matching full policy/model/snapshot lineage")
    required = {"symbol", "open_time", "probability_positive"}
    if not predictions.columns.is_unique or not required.issubset(predictions):
        raise DatasetError("ML predictions require unique symbol/time/probability columns")
    if (
        not pd.api.types.is_integer_dtype(predictions.open_time)
        or pd.api.types.is_bool_dtype(predictions.open_time)
        or predictions.open_time.isna().any()
        or (predictions.open_time % HOUR_US != 0).any()
    ):
        raise DatasetError("ML timestamps must be integer hourly UTC microseconds")
    keys = list(zip(predictions.open_time, predictions.symbol, strict=True))
    if keys != sorted(keys) or len(set(keys)) != len(keys):
        raise DatasetError("ML predictions require chronological unique time/symbol keys")
    if not set(predictions.symbol).issubset(policy.payoffs.means_bps):
        raise DatasetError("ML prediction symbol has no frozen TRAIN payoff")
    parts = []
    readiness = max(policy.calibration.available_after_us, policy.payoffs.available_after_us)
    for symbol, group in predictions.groupby("symbol", sort=True):
        out = group.copy().reset_index(drop=True)
        raw = out.probability_positive.to_numpy(dtype=float)
        finite = np.isfinite(raw)
        if ((raw[finite] < 0) | (raw[finite] > 1)).any():
            raise DatasetError("finite probabilities must be in [0,1]")
        calibrated = np.full(len(out), np.nan)
        calibrated[finite] = policy.calibration.probabilities(pd.Series(raw[finite]))
        up, down = policy.payoffs.means_bps[str(symbol)]
        gross = calibrated * up + (1 - calibrated) * down
        cost = policy.cost_sides * policy.fees.cost_bps(str(symbol))
        net = np.sign(gross) * np.maximum(np.abs(gross) - cost, 0)
        times = out.open_time.to_numpy(dtype=np.int64)
        # A window crossing any absent interval is unavailable. No gaps are filled.
        steps = pd.Series(times).diff().eq(HOUR_US)
        consecutive = steps.rolling(policy.window - 1, min_periods=policy.window - 1).sum()
        continuous = consecutive.eq(policy.window - 1).to_numpy()
        score = zscore(pd.Series(net), policy.window).to_numpy()
        usable = continuous & np.isfinite(score)
        value = np.where(usable, np.clip(score, -1, 1), np.nan)
        # Normalisation must not create trades inside cost or reverse the expected edge.
        value = np.where(usable & ((net == 0) | (np.sign(value) != np.sign(net))), 0, value)
        out["decision_time"] = times + HOUR_US
        out["probability_calibrated"] = calibrated
        out["gross_edge_bps"] = gross
        out["expected_cost_bps"] = cost
        out["net_edge_bps"] = net
        out["trailing_zscore"] = score
        out["diagnostic_alpha"] = value
        out["available"] = usable & (out.decision_time.to_numpy() >= readiness)
        out["alpha"] = np.where(out.available, value, np.nan)
        parts.append(out)
    if not parts:
        raise DatasetError("ML predictions cannot be empty")
    diagnostics = pd.concat(parts).sort_values(["open_time", "symbol"]).reset_index(drop=True)
    values = tuple(
        AlphaValue(
            symbol=symbol,
            timestamp=int(timestamp),
            status=AlphaStatus.OK if available else AlphaStatus.UNAVAILABLE,
            value=float(value) if available else None,
            lineage=lineage,
        )
        for symbol, timestamp, available, value in zip(
            diagnostics.symbol.tolist(),
            diagnostics.decision_time.tolist(),
            diagnostics.available.tolist(),
            diagnostics.alpha.tolist(),
            strict=True,
        )
    )
    return MLAlphaSeries(values, diagnostics, config_hash(policy))
