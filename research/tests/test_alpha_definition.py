"""YAML validation and real, rolled-back registry integration for step 085."""

import math
import runpy
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import Connection, text

from helios.alpha.definition import (
    AlphaDefinition,
    AlphaProvenance,
    load_alpha_definition,
    register_alpha_definition,
)
from helios.common.config import ConfigError, config_hash
from helios.registry.api import Provenance, RegistryError, get_alpha
from helios.registry.lifecycle import INITIAL, AlphaState

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "configs/alphas/examples"
main = runpy.run_path(str(ROOT / "scripts/register_alpha.py"))["main"]


def definition(**changes: object) -> AlphaDefinition:
    values: dict[str, object] = {
        "alpha_id": "t_yaml_alpha",
        "version": 1,
        "name": "YAML test alpha",
        "provenance": "QUANT",
        "feature_set_version": "v1",
        "horizon_family": "H-HOURLY",
        "horizon_periods": 24,
        "params": {"scale": 0.5},
        "expression": "sign(log_return_24) * scale",
        "author": "test_author",
        "code_commit": "a" * 40,
    }
    return AlphaDefinition.model_validate(values | changes)


@pytest.mark.parametrize("path", sorted(EXAMPLES.glob("*.yaml")), ids=lambda p: p.stem)
def test_examples_load_and_adapt(path: Path) -> None:
    loaded = load_alpha_definition(path)
    stored = loaded.to_registry()
    assert stored.alpha_id == loaded.alpha_id
    assert len(stored.code_commit) == 40
    assert stored.spec["params"] == loaded.params
    assert stored.horizon_family == loaded.horizon_family
    assert stored.provenance is (
        Provenance.HUMAN if loaded.provenance is AlphaProvenance.QUANT else Provenance.ML
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"alpha_id": "Invalid ID"},
        {"version": 0},
        {"version": True},
        {"version": "1"},
        {"horizon_periods": 0},
        {"horizon_periods": 1.5},
        {"provenance": "human"},
        {"horizon_family": "H-DAILY"},
        {"feature_set_version": "  "},
        {"expression": "  "},
        {"expression": None},
        {"model_ref": "example://model"},
        {"expression": None, "model_ref": "example://model"},
        {"author": " "},
        {"code_commit": "abc123"},
        {"state": "PROMOTED"},
        {"unexpected_field": "typo"},
        {"params": {"nested": [math.nan]}},
        {"params": {"nested": {"infinite": math.inf}}},
    ],
)
def test_invalid_definitions_fail_before_registration(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        definition(**changes)


def test_ml_accepts_a_model_or_generated_expression() -> None:
    model = definition(provenance="ML", expression=None, model_ref="example://model/v1")
    assert model.to_registry().spec == {
        "model_ref": "example://model/v1",
        "params": {"scale": 0.5},
        "output": model.output.model_dump(mode="json"),
    }
    generated = definition(provenance="ML")
    assert generated.to_registry().provenance is Provenance.ML


def test_model_is_frozen_and_adapter_does_not_share_params() -> None:
    idea = definition()
    with pytest.raises(ValidationError):
        idea.version = 2  # type: ignore[misc]
    record = idea.to_registry()
    record.spec["params"]["scale"] = 9
    assert idea.params["scale"] == 0.5


def test_no_expression_is_executed(tmp_path: Path) -> None:
    marker = tmp_path / "must_not_exist"
    expression = f"__import__('pathlib').Path({str(marker)!r}).touch()"
    idea = definition(expression=expression)
    assert idea.to_registry().spec["expression"] == expression
    assert not marker.exists()  # static DSL rejection belongs to subsequent steps


def test_stable_fingerprint_and_parameter_changes() -> None:
    idea = definition(params={"a": 1, "b": [2, 3]})
    reordered = definition(params={"b": [2, 3], "a": 1})
    assert config_hash(idea) == config_hash(reordered)
    assert config_hash(idea) != config_hash(definition(params={"a": 2, "b": [2, 3]}))


@pytest.mark.parametrize("contents", ["[]", "alpha_id: [", "alpha_id: missing_fields"])
def test_bad_yaml_has_a_config_error(tmp_path: Path, contents: str) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text(contents)
    with pytest.raises(ConfigError):
        load_alpha_definition(path)


def test_check_only_cli_does_not_open_database(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden() -> None:
        pytest.fail("check-only must not contact PostgreSQL")

    monkeypatch.setitem(main.__globals__, "get_engine", forbidden)
    assert main(["--file", str(EXAMPLES / "btc_hourly_momentum.yaml"), "--check-only"]) == 0


def test_cli_missing_file_is_an_error(tmp_path: Path) -> None:
    assert main(["--file", str(tmp_path / "absent.yaml"), "--check-only"]) == 2


@pytest.mark.parametrize("path", sorted(EXAMPLES.glob("*.yaml")), ids=lambda p: p.stem)
def test_examples_register_as_draft_without_results(connection: Connection, path: Path) -> None:
    loaded = load_alpha_definition(path)
    # Test IDs never collide with real registered examples; fixture rolls back every insert.
    loaded = loaded.model_copy(update={"alpha_id": "t_" + path.stem})
    stored = register_alpha_definition(connection, loaded)
    round_trip = get_alpha(connection, stored.alpha_id, stored.version)
    assert round_trip.spec == loaded.to_registry().spec
    assert round_trip.code_commit == loaded.code_commit
    assert round_trip.created_at is not None
    assert INITIAL is AlphaState.DRAFT
    assert (
        connection.execute(
            text("SELECT count(*) FROM alpha_results WHERE alpha_id = :id AND version = :version"),
            {"id": stored.alpha_id, "version": stored.version},
        ).scalar_one()
        == 0
    )


def test_duplicate_refused_and_new_version_preserves_old_spec(connection: Connection) -> None:
    register_alpha_definition(connection, definition())
    # Savepoint avoids leaving PostgreSQL's transaction aborted after the expected error.
    with pytest.raises(RegistryError, match="new version"):
        with connection.begin_nested():
            register_alpha_definition(connection, definition())
    register_alpha_definition(connection, definition(version=2, params={"scale": 1.0}))
    assert get_alpha(connection, "t_yaml_alpha", 1).spec["params"] == {"scale": 0.5}
    assert get_alpha(connection, "t_yaml_alpha", 2).spec["params"] == {"scale": 1.0}
