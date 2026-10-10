"""Final alpha bounding and a stored, versioned scale convention (step 092)."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Literal

import numpy as np
import pandas as pd
from pydantic import field_validator

from helios.alpha.cross_sectional import evaluate_universe_expression
from helios.alpha.errors import DSLEvaluationError
from helios.alpha.evaluator import AlphaSeries, _check_frame, evaluate_expression
from helios.common.config import HeliosConfig
from helios.features.runner import FeatureFrame

if TYPE_CHECKING:
    from helios.alpha.definition import AlphaDefinition


class OutputConvention(HeliosConfig):
    """Fixed alpha bounds, with a positive scale reserved for position mapping."""

    convention: Literal["clip_unit_v1"] = "clip_unit_v1"
    lower: Literal[-1] = -1
    upper: Literal[1] = 1
    position_scale: float = 1.0

    @field_validator("lower", "upper", "position_scale", mode="before")
    @classmethod
    def _numeric(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("output bounds and position_scale must be numeric")
        return value

    @field_validator("position_scale")
    @classmethod
    def _positive_finite(cls, value: float) -> float:
        if not math.isfinite(value) or value <= 0:
            raise ValueError("position_scale must be finite and positive")
        return value


@dataclass(frozen=True)
class BoundedAlphaSeries(AlphaSeries):
    """Final values plus the exact convention used to produce them."""

    output: OutputConvention


def bound_alpha(
    alpha: AlphaSeries, *, output: OutputConvention | None = None
) -> BoundedAlphaSeries:
    """Clip only finite available final values; never turn infinity into a position."""
    frame = FeatureFrame(
        alpha.symbol,
        alpha.open_time,
        alpha.values.to_frame("alpha"),
        alpha.available.to_frame("alpha"),
    )
    _check_frame(frame, allow_empty=True)
    if not pd.api.types.is_numeric_dtype(alpha.values.dtype) or (
        pd.api.types.is_bool_dtype(alpha.values.dtype)
        or pd.api.types.is_complex_dtype(alpha.values.dtype)
    ):
        raise DSLEvaluationError("alpha values must be real numeric values")
    if not pd.api.types.is_bool_dtype(alpha.available.dtype) or alpha.available.isna().any():
        raise DSLEvaluationError("alpha availability must be a non-null boolean mask")
    convention = OutputConvention() if output is None else output
    values = alpha.values.to_numpy(dtype=np.float64, na_value=np.nan, copy=True)
    available = alpha.available.to_numpy(dtype=bool, copy=True) & np.isfinite(values)
    values = np.where(available, np.clip(values, convention.lower, convention.upper), np.nan)
    return BoundedAlphaSeries(
        alpha.symbol,
        alpha.open_time.copy(),
        pd.Series(values, index=alpha.values.index.copy(), name="alpha", dtype="float64"),
        pd.Series(available, index=alpha.values.index.copy(), name="available", dtype=bool),
        convention,
    )


def evaluate_definition(
    definition: AlphaDefinition, features: FeatureFrame, *, interval: str | None = None
) -> BoundedAlphaSeries:
    """Evaluate a definition's full expression, then apply its stored final bounds."""
    if definition.expression is None:
        raise DSLEvaluationError("model references require a separate model inference pipeline")
    raw = evaluate_expression(
        definition.expression, features, params=definition.params, interval=interval
    )
    return bound_alpha(raw, output=definition.output)


def evaluate_universe_definition(
    definition: AlphaDefinition,
    features: Mapping[str, FeatureFrame],
    *,
    listing_dates: Mapping[str, date],
    interval: str | None = None,
) -> dict[str, BoundedAlphaSeries]:
    """Complete all cross/time operations before bounding each coin's final alpha."""
    if definition.expression is None:
        raise DSLEvaluationError("model references require a separate model inference pipeline")
    raw = evaluate_universe_expression(
        definition.expression,
        features,
        listing_dates=listing_dates,
        params=definition.params,
        interval=interval,
    )
    return {symbol: bound_alpha(alpha, output=definition.output) for symbol, alpha in raw.items()}
