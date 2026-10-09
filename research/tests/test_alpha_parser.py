"""Positive grammar, adversarial syntax and resource bounds for step 086."""

import ast
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from helios.alpha.definition import load_alpha_definition
from helios.alpha.parser import (
    ALLOWED_NODE_TYPES,
    FUNCTION_ARITY,
    MAX_DEPTH,
    MAX_NODES,
    MAX_SOURCE_LENGTH,
    DSLParseError,
    parse_expression,
)


def test_plan_example_preserves_the_formula_tree() -> None:
    tree = parse_expression("zscore(ret_1, 24) * -1")
    assert isinstance(tree, ast.Expression)
    assert isinstance(tree.body, ast.BinOp)
    assert isinstance(tree.body.op, ast.Mult)
    assert isinstance(tree.body.left, ast.Call)
    assert isinstance(tree.body.left.func, ast.Name)
    assert tree.body.left.func.id == "zscore"
    assert ast.unparse(tree) == "zscore(ret_1, 24) * -1"


@pytest.mark.parametrize(
    "source",
    [
        "x + y - z * 2 / 4",
        "+x + -y",
        "(x + y) / (z - 0.25)",
        "1e-3",
        "lag(ts_mean(log_return_1, 24), 1)",
        "clip(-zscore(log_return_1, 168), -1, 1)",
        "where(signal, 1, -1)",
        "  sign(log_return_24)  \n",
    ],
)
def test_supported_numeric_grammar(source: str) -> None:
    tree = parse_expression(source)
    assert all(type(node) in ALLOWED_NODE_TYPES for node in ast.walk(tree))


@pytest.mark.parametrize("function,arity", FUNCTION_ARITY.items())
def test_every_whitelisted_function_accepts_its_positional_signature(
    function: str, arity: int
) -> None:
    arguments = ["x", "24", "1"][:arity]
    assert isinstance(parse_expression(f"{function}({', '.join(arguments)})").body, ast.Call)


@pytest.mark.parametrize("function,arity", FUNCTION_ARITY.items())
def test_wrong_function_arity_is_rejected(function: str, arity: int) -> None:
    with pytest.raises(DSLParseError, match="positional arguments"):
        parse_expression(f"{function}({', '.join(['x'] * (arity + 1))})")
    with pytest.raises(DSLParseError, match="positional arguments"):
        parse_expression(f"{function}()")


@pytest.mark.parametrize(
    "source",
    [
        "x.close",
        "x[0]",
        "x[-1]",
        "x[1:]",
        "[x]",
        "(x, y)",
        "{x}",
        "{'x': 1}",
        "[x for x in y]",
        "(x for x in y)",
        "lambda x: x",
        "(x := 1)",
        "x if y else z",
        "x and y",
        "not x",
        "x > y",
        "x == y",
        "x in y",
        "x ** 2",
        "x // 2",
        "x % 2",
        "x @ y",
        "x | y",
        "x << 1",
        "~x",
        "np.mean(x)",
        "__import__('os')",
        "open('file')",
        "eval(x)",
        "mean(x)",
        "cs_rank(x)",
        "(lambda x: x)(1)",
        "sign(x)(1)",
        "sign(*x)",
        "zscore(x, window=24)",
        "sign(**x)",
        "True",
        "False",
        "None",
        "'text'",
        "b'bytes'",
        "1j",
        "...",
        "f'{x}'",
        "1e309",
        "_private",
        "x__class__",
        "Feature",
        "α",
        "x; y",
        "x = 1",
        "import os",
        "",
        "   ",
        "x +",
        "x\x00",
        "await x",
    ],
)
def test_non_dsl_python_is_rejected(source: str) -> None:
    with pytest.raises(DSLParseError):
        parse_expression(source)


def test_expression_cannot_create_a_file(tmp_path: Path) -> None:
    marker = tmp_path / "not_executed"
    with pytest.raises(DSLParseError):
        parse_expression(f"__import__('pathlib').Path({str(marker)!r}).touch()")
    assert not marker.exists()


@pytest.mark.parametrize("source", ["ｘ", "ｓｉｇｎ(x)", "sign(ｘ)"])
def test_unicode_normalization_cannot_bypass_ascii_identifiers(source: str) -> None:
    with pytest.raises(DSLParseError, match="identifier"):
        parse_expression(source)


def test_all_nodes_are_checked_even_in_nested_arguments() -> None:
    with pytest.raises(DSLParseError):
        parse_expression("where(x, sign(y), clip(z.__class__, -1, 1))")


def test_length_node_depth_and_numeric_bounds() -> None:
    with pytest.raises(DSLParseError, match="characters"):
        parse_expression("x" * (MAX_SOURCE_LENGTH + 1))
    # Balanced tree stays shallow enough to exercise the separate node-count bound.
    formula = "x"
    for _ in range(7):
        formula = f"({formula} + {formula})"
    assert len(list(ast.walk(ast.parse(formula, mode="eval")))) > MAX_NODES
    with pytest.raises(DSLParseError, match="AST nodes"):
        parse_expression(formula)
    with pytest.raises(DSLParseError, match="AST depth"):
        parse_expression("-" * (MAX_DEPTH + 1) + "x")
    with pytest.raises(DSLParseError, match="finite"):
        parse_expression("9" * 400)


@pytest.mark.parametrize("source", [None, 24, b"x"])
def test_non_string_input_has_a_parser_error(source: object) -> None:
    with pytest.raises(DSLParseError, match="string"):
        parse_expression(source)  # type: ignore[arg-type]


def test_structure_does_not_claim_feature_binding_or_causality() -> None:
    assert isinstance(parse_expression("unknown_feature + scale").body, ast.BinOp)
    # Lag/window semantic validation is explicitly step 090, not structural parsing.
    assert isinstance(parse_expression("lag(x, -1)").body, ast.Call)


def test_existing_quant_yaml_expressions_parse() -> None:
    examples = Path(__file__).resolve().parents[2] / "configs/alphas/examples"
    for path in examples.glob("*.yaml"):
        idea = load_alpha_definition(path)
        if idea.expression is not None:
            parse_expression(idea.expression)


@settings(max_examples=100, deadline=None)
@given(st.text(max_size=200))
def test_arbitrary_text_has_only_a_validated_tree_or_parser_error(source: str) -> None:
    try:
        tree = parse_expression(source)
    except DSLParseError:
        return
    assert all(type(node) in ALLOWED_NODE_TYPES for node in ast.walk(tree))
