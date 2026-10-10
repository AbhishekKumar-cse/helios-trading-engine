"""Structural validation for the alpha DSL (step 086), without executing Python.

Returns an ast.Expression for subsequent interpretation. Feature/parameter binding,
window/lag causality checks and evaluation belong to later steps, not this parser.
"""

from __future__ import annotations

import ast
import math
import re
from types import MappingProxyType

MAX_SOURCE_LENGTH = 4096
MAX_NODES = 256
MAX_DEPTH = 32

ALLOWED_NODE_TYPES = frozenset(
    {
        ast.Expression,
        ast.BinOp,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.UnaryOp,
        ast.UAdd,
        ast.USub,
        ast.Call,
        ast.Name,
        ast.Load,
        ast.Constant,
    }
)
FUNCTION_ARITY = MappingProxyType(
    {
        "zscore": 2,
        "ts_mean": 2,
        "ts_std": 2,
        "rank_ts": 2,
        "lag": 2,
        "sign": 1,
        "clip": 3,
        "where": 3,
        "cs_rank": 1,
        "cs_demean": 1,
    }
)
IDENTIFIER = re.compile(r"[a-z][a-z0-9_]*", flags=re.ASCII)


class DSLParseError(ValueError):
    """An expression is malformed, outside the whitelist, or exceeds parser limits."""


def _validate_node(node: ast.AST, source: str) -> None:
    if type(node) not in ALLOWED_NODE_TYPES:
        raise DSLParseError(f"{type(node).__name__} is not allowed in the alpha DSL")
    if isinstance(node, ast.Name):
        if (
            not IDENTIFIER.fullmatch(node.id)
            or "__" in node.id
            or ast.get_source_segment(source, node) != node.id
        ):
            # Python normalizes Unicode identifiers; check the original spelling too.
            raise DSLParseError(f"invalid DSL identifier: {node.id!r}")
    elif isinstance(node, ast.Constant):
        # bool is a subclass of int; explicitly keep True/False out of numeric formulas.
        if isinstance(node.value, bool) or not isinstance(node.value, int | float):
            raise DSLParseError("only finite real numeric constants are allowed")
        try:
            finite = math.isfinite(node.value)
        except OverflowError:
            finite = False
        if not finite:
            raise DSLParseError("numeric constants must be finite and representable as float64")
    elif isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise DSLParseError("functions must be called directly by their DSL name")
        name = node.func.id
        if name not in FUNCTION_ARITY:
            raise DSLParseError(f"unknown DSL function: {name!r}")
        if node.keywords:
            raise DSLParseError("keyword arguments and ** unpacking are not allowed")
        if len(node.args) != FUNCTION_ARITY[name]:
            raise DSLParseError(f"{name} requires {FUNCTION_ARITY[name]} positional arguments")


def parse_expression(source: str) -> ast.Expression:
    """Parse a single whitelisted formula without executing Python or accessing data.

    Only +, -, *, /, unary +/- and the declared DSL functions are accepted.
    Calls take positional arguments. Names remain unresolved, so ret_1 in the plan's
    example is accepted syntactically without inventing a feature alias. Consumers
    must interpret this tree through the DSL evaluator, never Python evaluation.
    """
    if not isinstance(source, str):
        raise DSLParseError("expression must be a string")
    if len(source) > MAX_SOURCE_LENGTH:
        raise DSLParseError(f"expression exceeds {MAX_SOURCE_LENGTH} characters")
    source = source.strip()
    if not source:
        raise DSLParseError("expression must not be empty")
    try:
        tree = ast.parse(source, mode="eval")
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise DSLParseError("invalid expression syntax") from exc

    pending: list[tuple[ast.AST, int]] = [(tree, 0)]
    count = 0
    while pending:
        node, depth = pending.pop()
        count += 1
        if count > MAX_NODES:
            raise DSLParseError(f"expression exceeds {MAX_NODES} AST nodes")
        if depth > MAX_DEPTH:
            raise DSLParseError(f"expression exceeds AST depth {MAX_DEPTH}")
        _validate_node(node, source)
        pending.extend((child, depth + 1) for child in ast.iter_child_nodes(node))
    return tree
