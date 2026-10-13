"""Explicit alpha validity before performance metrics or selection gates (106)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import Field, StrictInt

from helios.alpha.evaluator import AlphaSeries
from helios.common.config import HeliosConfig, canonical_json, config_hash
from helios.sim.positions import SimulationError, _times


class ValidityConfig(HeliosConfig):
    warmup_rows: StrictInt = Field(default=0, ge=0)
    min_periods: StrictInt = Field(default=2, ge=2)
    convention: Literal["explicit_warmup_complete_v1"] = "explicit_warmup_complete_v1"


class InvalidReason(StrEnum):
    DATA_GAPS = "DATA_GAPS"
    NON_FINITE_PRICES = "NON_FINITE_PRICES"
    TOO_FEW_PERIODS = "TOO_FEW_PERIODS"
    NON_FINITE_ALPHA = "NON_FINITE_ALPHA"
    UNAVAILABLE_AFTER_WARMUP = "UNAVAILABLE_AFTER_WARMUP"
    CONSTANT_ALPHA = "CONSTANT_ALPHA"


@dataclass(frozen=True)
class ValidityResult:
    status: Literal["VALID", "INVALID"]
    reasons: tuple[InvalidReason, ...]
    symbol: str
    n_rows: int
    n_periods: int
    n_unavailable_after_warmup: int
    config_json: str
    config_hash: str
    input_hash: str

    @property
    def valid(self) -> bool:
        return self.status == "VALID"


def alpha_validity(alpha: AlphaSeries, *, config: ValidityConfig | None = None) -> ValidityResult:
    """Do not infer warm-up from the first finite value or drop later unavailable rows.

    The first post-warm-up row is the accounting boundary, so N such rows give
    N-1 observed return intervals. The default minimum is the statistical minimum
    for sample variance, not a claim of sufficient research evidence.
    """
    selected = (
        ValidityConfig() if config is None else ValidityConfig.model_validate(config.model_dump())
    )
    if (
        not alpha.values.index.is_unique
        or not alpha.available.index.equals(alpha.values.index)
        or not alpha.open_time.index.equals(alpha.values.index)
    ):
        raise SimulationError("alpha values, availability and timestamps must share a unique index")
    times = _times(alpha.open_time)
    column = alpha.values
    if (
        not pd.api.types.is_numeric_dtype(column.dtype)
        or pd.api.types.is_bool_dtype(column.dtype)
        or pd.api.types.is_complex_dtype(column.dtype)
    ):
        raise SimulationError("alpha validity requires real numeric values")
    if alpha.available.dtype != bool or alpha.available.isna().any():
        raise SimulationError("alpha validity requires boolean availability")
    values = np.asarray(column.to_numpy(na_value=np.nan, copy=True), dtype=np.float64)
    mask = alpha.available.to_numpy(dtype=bool, copy=True)
    usable = mask & np.isfinite(values)
    after = usable[selected.warmup_rows :]
    observed = values[selected.warmup_rows :][after]
    n_periods = max(0, len(after) - 1)
    reasons = []
    if n_periods < selected.min_periods:
        reasons.append(InvalidReason.TOO_FEW_PERIODS)
    if (mask & ~np.isfinite(values)).any():
        reasons.append(InvalidReason.NON_FINITE_ALPHA)
    missing = int((~after).sum())
    if missing:
        reasons.append(InvalidReason.UNAVAILABLE_AFTER_WARMUP)
    if len(observed) and np.all(observed == observed[0]):
        reasons.append(InvalidReason.CONSTANT_ALPHA)
    digest = hashlib.sha256(alpha.symbol.encode())
    for array in (times.astype("<i8"), values.astype("<f8"), mask.astype("u1")):
        digest.update(len(array).to_bytes(8, "little"))
        digest.update(array.tobytes())
    return ValidityResult(
        "INVALID" if reasons else "VALID",
        tuple(reasons),
        alpha.symbol,
        len(values),
        n_periods,
        missing,
        canonical_json(selected),
        config_hash(selected),
        digest.hexdigest(),
    )
