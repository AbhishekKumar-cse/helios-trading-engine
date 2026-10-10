"""Data-independent DSL binding and causal-control validation (step 090).

Validate source through the structural whitelist and then inspect every expression
branch before allocating series or computing any statistic. No data-derived controls,
future lags, unbounded reducers or arbitrary Python execution are permitted.
"""

from __future__ import annotations

import ast
import math
from collections.abc import Collection, Mapping
from typing import cast

from helios.alpha.errors import DSLEvaluationError
from helios.alpha.parser import FUNCTION_ARITY, IDENTIFIER, parse_expression
from helios.data.klines import KlineFormatError, interval_us


def _parameters(params: Mapping[str, object], feature_names: Collection[str]) -> dict[str, float]:
    result: dict[str, float] = {}
    for name, value in params.items():
        if not isinstance(name, str) or not IDENTIFIER.fullmatch(name) or "__" in name:
            raise DSLEvaluationError("parameter names must be valid DSL identifiers")
        if name in feature_names or name in FUNCTION_ARITY:
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


def _scalar(node: ast.expr, params: Mapping[str, float]) -> float:
    """Function controls depend only on explicit finite constants/parameters."""
    if isinstance(node, ast.Constant):
        value = float(cast(int | float, node.value))
    elif isinstance(node, ast.Name) and node.id in params:
        value = params[node.id]
    elif isinstance(node, ast.UnaryOp):
        value = _scalar(node.operand, params)
        if isinstance(node.op, ast.USub):
            value = -value
    elif isinstance(node, ast.BinOp):
        left, right = _scalar(node.left, params), _scalar(node.right, params)
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


def _count(node: ast.expr, params: Mapping[str, float], minimum: int) -> int:
    value = _scalar(node, params)
    if not value.is_integer() or value < minimum or value >= 2**63:
        raise DSLEvaluationError(f"window/lag must be an integer value >= {minimum}, below 2**63")
    return int(value)


def _validate_tree(
    tree: ast.Expression,
    feature_names: Collection[str],
    params: Mapping[str, float],
    interval: str | None,
) -> None:
    """Internal semantic pass over a tree already checked by parse_expression."""
    if interval is not None:
        try:
            interval_us(interval)
        except KlineFormatError as exc:
            raise DSLEvaluationError(str(exc)) from exc
    names = set(feature_names)
    pending: list[ast.expr] = [tree.body]
    while pending:
        node = pending.pop()
        if isinstance(node, ast.Name):
            if node.id not in names and node.id not in params:
                raise DSLEvaluationError(f"unknown feature or parameter: {node.id!r}")
        elif isinstance(node, ast.UnaryOp):
            pending.append(node.operand)
        elif isinstance(node, ast.BinOp):
            pending.extend((node.left, node.right))
        elif isinstance(node, ast.Call):
            name = cast(ast.Name, node.func).id
            if name in {"lag", "zscore", "ts_mean", "ts_std", "rank_ts"}:
                _count(node.args[1], params, 2 if name in {"zscore", "ts_std"} else 1)
                if interval is None:
                    raise DSLEvaluationError("interval is required for rolling and lag functions")
            elif name == "clip":
                lower, upper = _scalar(node.args[1], params), _scalar(node.args[2], params)
                if lower > upper:
                    raise DSLEvaluationError("clip lower bound must not exceed upper bound")
            # Check both where branches even when a constant condition selects only one.
            pending.extend(node.args)


def validate_expression(
    source: str,
    *,
    feature_names: Collection[str],
    params: Mapping[str, object] | None = None,
    interval: str | None = None,
) -> ast.Expression:
    """Check syntax, bindings and causal scalar controls without evaluating rows.

    Feature names are the caller's declared evaluation schema, not invented aliases.
    Unknown/full-sample functions raise DSLParseError through the whitelist; unknown
    bindings and invalid controls raise DSLEvaluationError. A successful check does
    not certify input data, feature causality, availability, or trading performance.
    The evaluator reparses source and never trusts a caller-mutated returned tree.
    """
    tree = parse_expression(source)
    bindings = _parameters({} if params is None else params, feature_names)
    _validate_tree(tree, feature_names, bindings, interval)
    return tree
