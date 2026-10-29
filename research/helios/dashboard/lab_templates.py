"""Finite template expansion and causal session signals using HELIOS's existing DSL."""

from __future__ import annotations

import ast
import re
from typing import cast

import numpy as np
import pandas as pd

from helios.alpha.evaluator import AlphaSeries, Mask, _check_frame, _Evaluator
from helios.alpha.output import BoundedAlphaSeries, bound_alpha
from helios.alpha.parser import FUNCTION_ARITY
from helios.alpha.safety import _count, validate_expression
from helios.features.runner import FeatureFrame

FIELDS = ("close", "open", "high", "low", "volume")
TEMPLATES = {
    "Momentum": "clip(sign($field - lag($field, $lookback)), 0, 1)",
    "Reversal": "clip(-sign($field - lag($field, $lookback)), 0, 1)",
    "Z-score recovery": "clip(-zscore($field, $lookback), 0, 1)",
}
OPERATORS = tuple(
    name for name in FUNCTION_ARITY if name not in {"cs_rank", "cs_demean", "ts_backfill"}
)
VARIABLE = re.compile(r"\$([a-z][a-z0-9_]*)")


def expand(template: str, field: str, lookback: int, interval: str) -> str:
    if field not in FIELDS or type(lookback) is not int:
        raise ValueError("choose an observed OHLCV field and integer lookback")
    maximum = 60 if interval == "1m" else 4 if interval == "1h" else 0
    if not 1 <= lookback <= maximum:
        raise ValueError(f"{interval} session templates support 1–{maximum} completed bars")
    unknown = set(VARIABLE.findall(template)) - {"field", "lookback"}
    if unknown:
        raise ValueError("Undefined template variables: " + ", ".join(sorted(unknown)))
    expression = VARIABLE.sub(
        lambda match: field if match[1] == "field" else str(lookback), template
    )
    validate_session_expression(expression, interval)
    return expression


def validate_session_expression(expression: str, interval: str) -> None:
    maximum = 60 if interval == "1m" else 4 if interval == "1h" else 0
    if not maximum:
        raise ValueError("only retained minute/hourly session templates are executable")
    tree = validate_expression(expression, feature_names=FIELDS, interval=interval)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = cast(ast.Name, node.func).id
            if name not in OPERATORS:
                raise ValueError("this operator needs a different data/availability contract")
            if name not in {"clip", "where", "sign"}:
                if _count(node.args[1], {}, 1) > maximum:
                    raise ValueError(f"lookback exceeds the {maximum}-bar session limit")


class _SessionEvaluator(_Evaluator):
    """Same DSL arithmetic; continuity follows the observed NSE session's clock phase."""

    def contiguous(self, window: int) -> Mask:
        assert self.period is not None
        if window not in self.time_masks:
            times = self.frame.open_time.to_numpy(dtype=np.int64)
            known = np.zeros(len(times), dtype=bool)
            if window <= len(times):
                breaks = np.concatenate(([0], np.cumsum(np.diff(times) != self.period)))
                known[window - 1 :] = (
                    breaks[window - 1 :] - breaks[: len(times) - window + 1] == 0
                ) & ((times[window - 1 :] - times[0]) % self.period == 0)
            self.time_masks[window] = known
        return self.time_masks[window]


def expression_signal(frame: pd.DataFrame, expression: str, interval: str) -> BoundedAlphaSeries:
    validate_session_expression(expression, interval)
    if frame.session_date.nunique() != 1 or not frame.open_time.is_monotonic_increasing:
        raise ValueError("one chronological session required")
    values = frame[list(FIELDS)].astype(float)
    available = pd.DataFrame(np.isfinite(values), index=values.index, columns=values.columns)
    for name in FIELDS:
        available[name] &= values[name].ge(0) if name == "volume" else values[name].gt(0)
    features = FeatureFrame(str(frame.symbol.iloc[0]), frame.open_time, values, available)
    _check_frame(features)
    tree = validate_expression(expression, feature_names=FIELDS, interval=interval)
    computed, known = _SessionEvaluator(features, {}, interval).visit(tree.body)
    if not known.any():
        raise ValueError("No available signal values after session warmup; choose a shorter window")
    return bound_alpha(
        AlphaSeries(
            features.symbol,
            frame.open_time,
            pd.Series(computed, index=frame.index).clip(0, 1),
            pd.Series(known, index=frame.index),
        )
    )
