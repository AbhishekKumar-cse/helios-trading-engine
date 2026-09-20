"""Tests for recording results (step 065).

The central rule: a result cannot exist without the four things that let someone reproduce
it. Database tests run inside a transaction that is rolled back.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError
from registry_sql import GATE_CONFIG, SNAPSHOT
from sqlalchemy import Connection, text

from helios.common.lineage import RunContext
from helios.common.project_config import HorizonFamily
from helios.registry.api import AlphaDefinition, Provenance, RegistryError, register_definition
from helios.registry.experiments import ExperimentKind, register_experiment
from helios.registry.results import (
    AlphaResult,
    Split,
    Status,
    get_result,
    list_results,
    record_result,
    result_from_context,
)

COMMIT = "a" * 40
CONFIG_HASH = "b" * 64
SNAPSHOT_ID = "t-snapshot-0001"
GATES_ID = "t_gates_v1"
ALL_PASSED = {"G1": True, "G2": True, "G3": True, "G4": True, "G5": True, "G6": True}
EXPERIMENT: dict[str, int] = {"id": 0}  # filled in by the registry fixture


def result(**overrides: object) -> AlphaResult:
    values: dict[str, object] = {
        "experiment_id": EXPERIMENT["id"] or 1,
        "alpha_id": "t_result_alpha",
        "version": 1,
        "split": Split.VALID,
        "snapshot_id": SNAPSHOT_ID,
        "gate_config_id": GATES_ID,
        "sharpe": Decimal("1.5"),
        "annual_return": Decimal("0.25"),
        "turnover": Decimal("0.30"),
        "fitness": Decimal("1.4"),
        "periods": 8760,
        "gate_results": dict(ALL_PASSED),
        "code_commit": COMMIT,
        "config_hash": CONFIG_HASH,
        "seed": 0,
        "dirty": False,
    }
    return AlphaResult(**(values | overrides))


@pytest.fixture
def registry(connection: Connection) -> Connection:
    """A registered alpha, a gate configuration and a data snapshot to point at."""
    register_definition(
        connection,
        AlphaDefinition(
            alpha_id="t_result_alpha",
            version=1,
            name="alpha used by the result tests",
            provenance=Provenance.HUMAN,
            spec={"rule": "sign"},
            feature_set_version="v1",
            horizon_family=HorizonFamily.HOURLY,
            horizon_periods=1,
            author="abhishek",
            code_commit=COMMIT,
        ),
    )
    EXPERIMENT["id"] = register_experiment(
        connection,
        hypothesis="hourly momentum beats holding BTC after costs",
        params={"lookback_hours": 24},
        kind=ExperimentKind.ALPHA,
        author="abhishek",
    ).experiment_id
    connection.execute(
        text(GATE_CONFIG),
        {
            "config_id": GATES_ID,
            "turnover_min": 0.01,
            "turnover_max": 0.70,
            "stress": 2.0,
            "hash": CONFIG_HASH,
        },
    )
    connection.execute(text(SNAPSHOT), {"id": SNAPSHOT_ID, "commit": COMMIT})
    return connection


# ---------------------------------------------------------------- lineage is compulsory


@pytest.mark.parametrize("field", ["code_commit", "config_hash", "seed", "dirty", "snapshot_id"])
def test_a_result_without_its_lineage_is_refused(field: str) -> None:
    """The point of this step: these four fields have no defaults, so they cannot be left out."""
    values = result().model_dump()
    del values[field]
    del values["created_at"]
    with pytest.raises(ValidationError, match=field):
        AlphaResult(**values)


def test_a_half_written_commit_is_refused() -> None:
    with pytest.raises(ValidationError, match="40-character git commit"):
        result(code_commit="abc123")


def test_a_config_hash_that_is_not_a_sha256_is_refused() -> None:
    with pytest.raises(ValidationError, match="64-character sha256"):
        result(config_hash="not-a-hash")


def test_a_negative_seed_is_refused() -> None:
    with pytest.raises(ValidationError):
        result(seed=-1)


def test_the_run_id_is_generated_when_not_given() -> None:
    assert len(result().run_id) == 36  # a uuid


# ---------------------------------------------------------------- values that cannot be true


def test_negative_turnover_is_refused() -> None:
    with pytest.raises(ValidationError):
        result(turnover=Decimal("-0.1"))


def test_a_positive_drawdown_is_refused() -> None:
    with pytest.raises(ValidationError):
        result(max_drawdown=Decimal("0.2"))


def test_a_hit_rate_above_one_is_refused() -> None:
    with pytest.raises(ValidationError):
        result(hit_rate=Decimal("1.4"))


def test_zero_periods_is_refused() -> None:
    with pytest.raises(ValidationError):
        result(periods=0)


def test_an_invented_gate_name_is_refused() -> None:
    with pytest.raises(ValidationError, match="G1 ... G9"):
        result(gate_results={"G1": True, "looks_good": True})


def test_no_gate_results_at_all_is_refused() -> None:
    with pytest.raises(ValidationError):
        result(gate_results={})


# ---------------------------------------------------------------- promotion must be earned


def test_promotion_needs_every_gate(registry: Connection) -> None:
    with pytest.raises(ValidationError, match=r"cannot promote: \['G2'\]"):
        result(status=Status.PROMOTED, gate_results={**ALL_PASSED, "G2": False})


def test_promotion_on_the_train_split_is_refused() -> None:
    with pytest.raises(ValidationError, match="out-of-sample"):
        result(status=Status.PROMOTED, split=Split.TRAIN)


def test_promotion_from_a_dirty_folder_is_refused() -> None:
    """If the code was not committed, the result cannot be reproduced, so it cannot be used."""
    with pytest.raises(ValidationError, match="cannot be reproduced"):
        result(status=Status.PROMOTED, dirty=True)


def test_a_promotion_that_earned_it_is_accepted() -> None:
    promoted = result(status=Status.PROMOTED, split=Split.TEST)
    assert promoted.passed_all_gates is True


def test_a_failing_run_can_still_be_recorded(registry: Connection) -> None:
    """Failures are evidence too, and are kept."""
    failed = result(gate_results={**ALL_PASSED, "G1": False}, sharpe=Decimal("0.2"))
    stored = record_result(registry, failed)
    assert stored.status is Status.EVALUATED
    assert stored.passed_all_gates is False


# ---------------------------------------------------------------- building from a run context


def test_a_result_can_be_built_from_the_run_context() -> None:
    context = RunContext(
        code_commit=COMMIT,
        dirty=False,
        config_hash=CONFIG_HASH,
        data_snapshot_id=SNAPSHOT_ID,
        seed=7,
        created_at=datetime.now(UTC),
    )
    built = result_from_context(
        context,
        experiment_id=EXPERIMENT["id"] or 1,
        alpha_id="t_result_alpha",
        version=1,
        split=Split.VALID,
        gate_config_id=GATES_ID,
        sharpe=1.5,
        annual_return=0.25,
        turnover=0.3,
        fitness=1.4,
        periods=8760,
        gate_results=dict(ALL_PASSED),
    )
    assert built.code_commit == COMMIT
    assert built.config_hash == CONFIG_HASH
    assert built.snapshot_id == SNAPSHOT_ID
    assert built.seed == 7
    assert built.dirty is False


# ---------------------------------------------------------------- storing and reading


def test_a_result_is_stored(registry: Connection) -> None:
    stored = record_result(registry, result())
    assert stored.created_at is not None
    back = get_result(registry, stored.run_id)
    assert back.sharpe == Decimal("1.5")
    assert back.gate_results == ALL_PASSED
    assert back.split is Split.VALID


def test_metrics_keep_their_exact_decimals(registry: Connection) -> None:
    stored = record_result(registry, result(sharpe=Decimal("1.2345678901")))
    assert get_result(registry, stored.run_id).sharpe == Decimal("1.2345678901")


def test_the_same_run_cannot_be_recorded_twice(registry: Connection) -> None:
    first = record_result(registry, result())
    with pytest.raises(RegistryError, match="already recorded"):
        record_result(registry, result(run_id=first.run_id))


def test_a_result_for_an_unregistered_alpha_is_refused(registry: Connection) -> None:
    with pytest.raises(RegistryError, match="register the definition"):
        record_result(registry, result(alpha_id="t_ghost_alpha"))


def test_a_result_pointing_at_unknown_data_is_refused(registry: Connection) -> None:
    with pytest.raises(RegistryError, match="snapshot .* is unknown"):
        record_result(registry, result(snapshot_id="t-no-such-data"))


def test_a_result_with_an_unknown_gate_config_is_refused(registry: Connection) -> None:
    with pytest.raises(RegistryError, match="gate configuration .* is unknown"):
        record_result(registry, result(gate_config_id="t_no_such_gates"))


def test_an_unknown_run_is_refused(registry: Connection) -> None:
    with pytest.raises(RegistryError, match="is not recorded"):
        get_result(registry, "no-such-run")


def test_runs_can_be_listed_and_filtered(registry: Connection) -> None:
    record_result(registry, result(split=Split.TRAIN))
    record_result(registry, result(split=Split.VALID))
    record_result(registry, result(split=Split.TEST, status=Status.PROMOTED))

    mine = list_results(registry, alpha_id="t_result_alpha")
    assert len(mine) == 3
    assert len(list_results(registry, alpha_id="t_result_alpha", split=Split.TEST)) == 1
    promoted = list_results(registry, alpha_id="t_result_alpha", status=Status.PROMOTED)
    assert len(promoted) == 1
    assert promoted[0].split is Split.TEST


def test_nothing_is_left_behind(connection: Connection) -> None:
    leaked = connection.execute(
        text("SELECT count(*) FROM alpha_results WHERE alpha_id LIKE 't\\_%'")
    ).scalar_one()
    assert leaked == 0
