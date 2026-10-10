"""Shared errors for DSL binding, semantic validation and evaluation."""


class DSLEvaluationError(ValueError):
    """An expression cannot be evaluated against supplied features/parameters."""
