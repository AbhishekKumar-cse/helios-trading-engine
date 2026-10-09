"""Alpha arithmetic and trailing DSL functions with explicit availability (088–089).

The only public evaluation entry point parses source itself. It never accepts a
caller-mutated AST for Python execution, and never invokes eval or compile.
"""

from __future__ import annotations

import ast
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

import numpy as np
import numpy.typing as npt
import pandas as pd

from helios.alpha.parser import FUNCTION_ARITY, IDENTIFIER, parse_expression
from helios.data.klines import KlineFormatError, interval_us
from helios.features.helpers import rank_ts, zscore
from helios.features.runner import FeatureFrame

Values = npt.NDArray[np.float64]
Mask = npt.NDArray[np.bool_]


class DSLEvaluationError(ValueError):
    """An expression cannot be evaluated against the supplied features/parameters."""


@dataclass(frozen=True)
class AlphaSeries:
    """One coin's raw alpha values; false availability always accompanies NaN."""

    symbol: str
    open_time: pd.Series
    values: pd.Series
    available: pd.Series

    @property
    def rows(self) -> int:
        return len(self.values)


def _check_frame(frame: FeatureFrame) -> None:
    if frame.rows == 0:
        raise DSLEvaluationError("there are no feature rows to evaluate")
    if not frame.values.columns.is_unique or not frame.available.columns.equals(
        frame.values.columns
    ):
        raise DSLEvaluationError("feature and availability columns must match and be unique")
    if (
        not frame.values.index.is_unique
        or not frame.available.index.equals(frame.values.index)
        or not frame.open_time.index.equals(frame.values.index)
    ):
        raise DSLEvaluationError("features, availability and timestamps must share a unique index")
    times = frame.open_time
    if (
        not pd.api.types.is_integer_dtype(times.dtype)
        or pd.api.types.is_bool_dtype(times.dtype)
        or times.isna().any()
        or not times.is_monotonic_increasing
        or times.duplicated().any()
    ):
        raise DSLEvaluationError("timestamps must be unique chronological UTC microsecond integers")


def _parameters(params: Mapping[str, object], frame: FeatureFrame) -> dict[str, float]:
    result: dict[str, float] = {}
    for name, value in params.items():
        if not isinstance(name, str) or not IDENTIFIER.fullmatch(name) or "__" in name:
            raise DSLEvaluationError("parameter names must be valid DSL identifiers")
        if name in frame.values.columns or name in FUNCTION_ARITY:
            raise DSLEvaluationError(f"parameter {name!r} collides with a feature or function name")
        if type(value) not in (int, float):
            raise DSLEvaluationError(f"parameter {name!r} must be a finite numeric scalar")
        try:
            number = float(cast(int | float, value))
        except (OverflowError, ValueError) as exc:
            raise DSLEvaluationError(f"parameter {name!r} is not representable as float64") from exc
        if not math.isfinite(number):
            raise DSLEvaluationError(f"parameter {name!r} must be finite")
        result[name] = number
    return result


def _masked(values: Values, available: Mask) -> tuple[Values, Mask]:
    usable = available & np.isfinite(values)
    return np.where(usable, values, np.nan), usable


class _Evaluator:
    def __init__(self, frame: FeatureFrame, params: dict[str, float], interval: str | None) -> None:
        self.frame = frame
        self.params = params
        self.cache: dict[str, tuple[Values, Mask]] = {}
        try:
            self.period = None if interval is None else interval_us(interval)
        except KlineFormatError as exc:
            raise DSLEvaluationError(str(exc)) from exc
        self.time_masks: dict[int, Mask] = {}

    def scalar(self, node: ast.expr) -> float:
        """Controls are constants/parameters, never feature-dependent or full-sample."""
        if isinstance(node, ast.Constant):
            value = float(cast(int | float, node.value))
        elif isinstance(node, ast.Name) and node.id in self.params:
            value = self.params[node.id]
        elif isinstance(node, ast.UnaryOp):
            value = self.scalar(node.operand)
            if isinstance(node.op, ast.USub):
                value = -value
        elif isinstance(node, ast.BinOp):
            left, right = self.scalar(node.left), self.scalar(node.right)
            if isinstance(node.op, ast.Add):
                value = left + right
            elif isinstance(node.op, ast.Sub):
                value = left - right
            elif isinstance(node.op, ast.Mult):
                value = left * right
            elif isinstance(node.op, ast.Div) and right != 0:
                value = left / right
            else:
                raise DSLEvaluationError("invalid scalar control arithmetic")
        else:
            raise DSLEvaluationError("function controls must use scalar constants or parameters")
        if not math.isfinite(value):
            raise DSLEvaluationError("function controls must be finite")
        return value

    def count(self, node: ast.expr, minimum: int) -> int:
        value = self.scalar(node)
        if not value.is_integer() or value < minimum or value >= 2**63:
            raise DSLEvaluationError(
                f"window/lag must be an integer value >= {minimum}, below 2**63"
            )
        return int(value)

    def contiguous(self, window: int) -> Mask:
        if self.period is None:
            raise DSLEvaluationError("interval is required for rolling and lag functions")
        if window not in self.time_masks:
            times = self.frame.open_time.to_numpy(dtype=np.int64)
            result = np.zeros(self.frame.rows, dtype=bool)
            if window <= self.frame.rows:
                breaks = np.concatenate(([0], np.cumsum(np.diff(times) != self.period)))
                result[window - 1 :] = (
                    breaks[window - 1 :] - breaks[: self.frame.rows - window + 1] == 0
                ) & (times[window - 1 :] % self.period == 0)
            self.time_masks[window] = result
        return self.time_masks[window]

    def call(self, node: ast.Call) -> tuple[Values, Mask]:
        name = cast(ast.Name, node.func).id  # direct whitelisted calls only, checked by parser
        values, available = self.visit(node.args[0])
        if name == "sign":
            return _masked(np.sign(values), available)
        if name == "clip":
            lower, upper = self.scalar(node.args[1]), self.scalar(node.args[2])
            if lower > upper:
                raise DSLEvaluationError("clip lower bound must not exceed upper bound")
            return _masked(np.clip(values, lower, upper), available)
        if name == "where":
            yes, yes_available = self.visit(node.args[1])
            no, no_available = self.visit(node.args[2])
            choose_yes = values != 0
            return _masked(
                np.where(choose_yes, yes, no),
                available & np.where(choose_yes, yes_available, no_available),
            )
        if name == "lag":
            periods = self.count(node.args[1], 1)
            contiguous = self.contiguous(periods + 1)
            shifted = np.full(self.frame.rows, np.nan)
            usable = np.zeros(self.frame.rows, dtype=bool)
            if periods < self.frame.rows:
                shifted[periods:] = values[:-periods]
                usable[periods:] = available[:-periods]
            return _masked(shifted, usable & contiguous)
        if name in {"zscore", "ts_mean", "ts_std", "rank_ts"}:
            window = self.count(node.args[1], 2 if name in {"zscore", "ts_std"} else 1)
            contiguous = self.contiguous(window)
            if window > self.frame.rows:
                return np.full(self.frame.rows, np.nan), contiguous
            series = pd.Series(values)
            with np.errstate(divide="ignore", invalid="ignore", over="ignore", under="ignore"):
                if name == "zscore":
                    computed = zscore(series, window)
                elif name == "rank_ts":
                    computed = rank_ts(series, window)
                elif name == "ts_mean":
                    computed = series.rolling(window, min_periods=window).mean()
                else:
                    computed = series.rolling(window, min_periods=window).std(ddof=1)
            return _masked(computed.to_numpy(dtype=np.float64), contiguous)
        raise DSLEvaluationError(f"unsupported DSL function: {name!r}")

    def constant(self, value: float) -> tuple[Values, Mask]:
        return np.full(self.frame.rows, value, dtype=np.float64), np.ones(
            self.frame.rows, dtype=bool
        )

    def feature(self, name: str) -> tuple[Values, Mask]:
        if name in self.params:
            return self.constant(self.params[name])
        if name not in self.frame.values.columns:
            raise DSLEvaluationError(f"unknown feature or parameter: {name!r}")
        if name not in self.cache:
            series = self.frame.values[name]
            mask = self.frame.available[name]
            if (
                not pd.api.types.is_numeric_dtype(series.dtype)
                or pd.api.types.is_complex_dtype(series.dtype)
                or pd.api.types.is_bool_dtype(series.dtype)
            ):
                raise DSLEvaluationError(f"feature {name!r} must contain real numeric values")
            if not pd.api.types.is_bool_dtype(mask.dtype) or mask.isna().any():
                raise DSLEvaluationError(f"feature {name!r} requires a non-null boolean mask")
            values = series.to_numpy(dtype=np.float64, na_value=np.nan, copy=True)
            available = mask.to_numpy(dtype=bool, copy=True)
            self.cache[name] = _masked(values, available)
        return self.cache[name]

    def visit(self, node: ast.expr) -> tuple[Values, Mask]:
        if isinstance(node, ast.Constant):
            return self.constant(float(cast(int | float, node.value)))
        if isinstance(node, ast.Name):
            return self.feature(node.id)
        if isinstance(node, ast.UnaryOp):
            values, available = self.visit(node.operand)
            if isinstance(node.op, ast.UAdd):
                return _masked(values, available)
            if isinstance(node.op, ast.USub):
                return _masked(-values, available)
        if isinstance(node, ast.BinOp):
            left, left_available = self.visit(node.left)
            right, right_available = self.visit(node.right)
            available = left_available & right_available
            # Floating errors are represented by unavailable rows, never silently zero-filled.
            with np.errstate(divide="ignore", invalid="ignore", over="ignore", under="ignore"):
                if isinstance(node.op, ast.Add):
                    values = left + right
                elif isinstance(node.op, ast.Sub):
                    values = left - right
                elif isinstance(node.op, ast.Mult):
                    values = left * right
                elif isinstance(node.op, ast.Div):
                    values = left / right
                else:
                    raise DSLEvaluationError("unsupported arithmetic operator")
            return _masked(values, available)
        if isinstance(node, ast.Call):
            return self.call(node)
        raise DSLEvaluationError(f"unsupported arithmetic node: {type(node).__name__}")


def evaluate_expression(
    source: str,
    features: FeatureFrame,
    *,
    params: Mapping[str, object] | None = None,
    interval: str | None = None,
) -> AlphaSeries:
    """Evaluate arithmetic and the eight DSL functions for one coin.

    Keep the source frame's row order, timestamps and symbol. Only referenced feature
    masks affect the result. No filling, sorting, alignment joins, normalization or
    final clipping is performed. Rolling/lag functions require an explicit interval.
    """
    tree = parse_expression(source)
    _check_frame(features)
    bindings = _parameters({} if params is None else params, features)
    values, available = _Evaluator(features, bindings, interval).visit(tree.body)
    return AlphaSeries(
        symbol=features.symbol,
        open_time=features.open_time.copy(),
        values=pd.Series(values, index=features.values.index.copy(), name="alpha", dtype="float64"),
        available=pd.Series(
            available, index=features.values.index.copy(), name="available", dtype=bool
        ),
    )
