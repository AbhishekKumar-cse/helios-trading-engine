"""Parameter accounting is derived, deterministic and stored without rewriting history."""

from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import Connection

from helios.alpha.complexity import count_free_parameters
from helios.alpha.definition import (
    AlphaDefinition,
    load_alpha_definition,
    register_alpha_definition,
)
from helios.alpha.parser import DSLParseError
from helios.common.config import ConfigError
from helios.registry.api import get_alpha


def idea(source: str = "-zscore(log_return_1, 168)", **changes: object) -> AlphaDefinition:
    return AlphaDefinition.model_validate(
        {
            "alpha_id": "t_counted_alpha",
            "version": 1,
            "name": "Counted alpha",
            "provenance": "QUANT",
            "feature_set_version": "v1",
            "horizon_family": "H-HOURLY",
            "horizon_periods": 1,
            "params": {},
            "expression": source,
            "author": "Test",
            "code_commit": "a" * 40,
            **changes,
        }
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("sign(log_return_24)", 0),
        ("-zscore(log_return_1, 168)", 1),
        ("zscore(taker_buy_ratio, 168)", 1),
        ("0.5 * x + 0.5 * y", 2),
        ("clip(lag(x, 1), -1, +1)", 3),
        ("where(0, ts_mean(x, 24), ts_std(y, 24))", 3),
        ("cs_demean(cs_rank(x))", 0),
        ("zscore(x, 24 + 24) / 1e2", 3),
        ("---2.5 * x", 1),
    ],
)
def test_literal_and_window_occurrences_count_once(source: str, expected: int) -> None:
    result = count_free_parameters(source)
    assert result.total == result.numeric_constants == expected
    assert result.named_parameters == ()


def test_reused_named_parameters_are_shared_and_unused_values_excluded() -> None:
    result = count_free_parameters(
        "a * ts_mean(x, window) + a * lag(y, window) + 2",
        params={"a": 0.5, "window": 24, "unused": [1, 2], "x_unused": 100},
    )
    assert result.numeric_constants == 1
    assert result.named_parameters == ("a", "window")
    assert result.total == 3


def test_feature_and_function_names_do_not_count() -> None:
    result = count_free_parameters("sign(x) + cs_rank(y)", params={"sign": 4, "other": 1})
    assert result.total == 0  # semantic collision checking remains the evaluator's responsibility


@pytest.mark.parametrize("value", [True, "24", [24], {"v": 24}, None, float("inf"), 10**400])
def test_referenced_parameters_must_be_finite_numeric_scalars(value: object) -> None:
    with pytest.raises(ValueError, match="parameter"):
        count_free_parameters("ts_mean(x, window)", params={"window": value})


@pytest.mark.parametrize("source", ["x.mean()", "mean(x)", "lag(x, k=1)", "__import__('os')"])
def test_counter_uses_parser_whitelist(source: str) -> None:
    with pytest.raises(DSLParseError):
        count_free_parameters(source)


def test_derived_count_is_in_definition_dump_and_registry_spec() -> None:
    definition = idea("a * ts_mean(x, w) + 1", params={"a": 0.5, "w": 24})
    assert definition.free_parameter_count == 3
    assert definition.model_dump()["free_parameter_count"] == 3
    spec = definition.to_registry().spec
    assert spec["free_parameter_count"] == 3
    assert spec["parameter_count_convention"] == "dsl_syntax_v1"
    assert definition.parameter_count_convention == "dsl_syntax_v1"


@pytest.mark.parametrize(
    "override",
    [
        {"free_parameter_count": 0},
        {"parameter_count_convention": "fake"},
    ],
)
def test_supplied_counts_and_rules_cannot_override_derivation(override: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        idea(**override)


def test_model_reference_reports_unknown_not_zero() -> None:
    definition = idea(expression=None, model_ref="example://trained", provenance="ML")
    assert definition.free_parameter_count is None
    assert definition.to_registry().spec["free_parameter_count"] is None
    assert definition.parameter_count_convention is None


def test_copied_expression_count_is_recomputed_not_stale() -> None:
    original = idea()
    revised = original.model_copy(update={"expression": "x + 1 + 2", "version": 2})
    assert original.free_parameter_count == 1
    assert revised.free_parameter_count == 2
    assert revised.to_registry().spec["free_parameter_count"] == 2


def test_definition_loading_counts_without_data_or_execution(tmp_path: Path) -> None:
    path = tmp_path / "alpha.yaml"
    path.write_text(
        "alpha_id: t_counted_yaml\nversion: 1\nname: Counted YAML\nprovenance: QUANT\n"
        "feature_set_version: v1\nhorizon_family: H-HOURLY\nhorizon_periods: 1\n"
        "expression: '-zscore(log_return_1, 168)'\nauthor: Test\ncode_commit: " + "a" * 40 + "\n"
    )
    assert load_alpha_definition(path).free_parameter_count == 1
    path.write_text(path.read_text().replace("-zscore(log_return_1, 168)", "mean(x)"))
    with pytest.raises(ConfigError):
        load_alpha_definition(path)


def test_structural_count_does_not_claim_semantic_or_causal_validation() -> None:
    # Negative lag remains rejected at evaluation/preflight, while its literal is countable.
    assert idea("lag(x, -1)").free_parameter_count == 1


def test_registry_preserves_counts_in_separate_versions(connection: Connection) -> None:
    first = idea()
    second = idea("0.5 * zscore(log_return_1, 168)", version=2)
    register_alpha_definition(connection, first)
    register_alpha_definition(connection, second)
    assert get_alpha(connection, first.alpha_id, 1).spec["free_parameter_count"] == 1
    assert get_alpha(connection, first.alpha_id, 2).spec["free_parameter_count"] == 2


def test_existing_registry_rows_are_not_retroactively_rewritten(connection: Connection) -> None:
    from helios.registry.api import register_definition

    legacy = idea().to_registry()
    del legacy.spec["free_parameter_count"]
    del legacy.spec["parameter_count_convention"]
    register_definition(connection, legacy)
    assert "free_parameter_count" not in get_alpha(connection, legacy.alpha_id, 1).spec
