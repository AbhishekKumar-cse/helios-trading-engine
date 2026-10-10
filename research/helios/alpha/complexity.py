"""Conservative, reproducible DSL parameter accounting (step 093)."""

from __future__ import annotations

import ast
import math
from collections.abc import Mapping
from dataclasses import dataclass

from helios.alpha.parser import parse_expression

PARAMETER_COUNT_CONVENTION = "dsl_syntax_v1"


@dataclass(frozen=True)
class ParameterCount:
    """Literal occurrences plus distinct numeric parameter names used by the formula."""

    numeric_constants: int
    named_parameters: tuple[str, ...]

    @property
    def total(self) -> int:
        return self.numeric_constants + len(self.named_parameters)


def count_free_parameters(
    source: str, *, params: Mapping[str, object] | None = None
) -> ParameterCount:
    """Count the validated formula without evaluation, simplification or data access.

    Each numeric literal occurrence counts once, including windows/lags/clip bounds
    and branch constants. A unary sign is not another parameter. Repeated named
    scalar parameters count once; unused parameters and feature/function names do
    not count. This syntactic proxy does not estimate independent fitted degrees
    of freedom, model weights, or search trials. Fixed output/position conventions
    are separate metadata, outside the formula count.
    """
    tree = parse_expression(source)
    bindings = {} if params is None else params
    functions = {id(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    constants = 0
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant):
            constants += 1
        elif isinstance(node, ast.Name) and id(node) not in functions and node.id in bindings:
            value = bindings[node.id]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(
                    f"referenced parameter {node.id!r} must be a finite numeric scalar"
                )
            try:
                finite = math.isfinite(value)
            except OverflowError:
                finite = False
            if not finite:
                raise ValueError(f"referenced parameter {node.id!r} must be finite as float64")
            names.add(node.id)
    return ParameterCount(constants, tuple(sorted(names)))
