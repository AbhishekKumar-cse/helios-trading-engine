"""Tests for pre-registered experiments (step 068).

The rule: a result cannot exist without a question that was written down before it.
Everything runs inside a rolled-back transaction.
"""

from decimal import Decimal

import pytest
from pydantic import ValidationError
from registry_sql import GATE_CONFIG, SNAPSHOT
from sqlalchemy import Connection, text

from helios.common.project_config import HorizonFamily
from helios.registry.api import AlphaDefinition, Provenance, RegistryError, register_definition
from helios.registry.experiments import (
    Experiment,
    ExperimentKind,
    ExperimentStatus,
    get_experiment,
    list_experiments,
    register_experiment,
    require_open_experiment,
    set_status,
)
from helios.registry.results import AlphaResult, Split, record_result

COMMIT = "a" * 40
CONFIG_HASH = "b" * 64
SNAPSHOT_ID = "t-experiment-snap"
GATES_ID = "t_experiment_gates"
ALPHA = "t_experiment_alpha"
ALL_PASSED = {"G1": True, "G2": True, "G3": True, "G4": True, "G5": True, "G6": True}
HYPOTHESIS = "hourly momentum on BTC beats holding it, after costs"


def an_experiment(connection: Connection, **overrides: object) -> Experiment:
    values: dict[str, object] = {
        "hypothesis": HYPOTHESIS,
        "params": {"lookback_hours": 24, "cap": 1.0},
        "kind": ExperimentKind.ALPHA,
        "author": "abhishek",
    }
    return register_experiment(connection, **(values | overrides))  # type: ignore[arg-type]


@pytest.fixture
def registry(connection: Connection) -> Connection:
    """An alpha, a gate configuration and a data snapshot to point at."""
    register_definition(
        connection,
        AlphaDefinition(
            alpha_id=ALPHA,
            version=1,
            name="alpha used by the experiment tests",
            provenance=Provenance.HUMAN,
            spec={"rule": "sign"},
            feature_set_version="v1",
            horizon_family=HorizonFamily.HOURLY,
            horizon_periods=1,
            author="abhishek",
            code_commit=COMMIT,
        ),
    )
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


def a_result(experiment_id: int, **overrides: object) -> AlphaResult:
    values: dict[str, object] = {
        "experiment_id": experiment_id,
        "alpha_id": ALPHA,
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


# ---------------------------------------------------------------- registering the question


def test_an_experiment_is_registered_with_its_parameters(connection: Connection) -> None:
    experiment = an_experiment(connection)
    assert experiment.experiment_id >= 1
    assert experiment.status is ExperimentStatus.PLANNED
    assert experiment.pre_registered_at is not None
    stored = get_experiment(connection, experiment.experiment_id)
    assert stored.hypothesis == HYPOTHESIS
    assert stored.params == {"lookback_hours": 24, "cap": 1.0}


def test_a_vague_hypothesis_is_refused(connection: Connection) -> None:
    """'it works' is not a hypothesis; it cannot be wrong, so it cannot be tested."""
    with pytest.raises(RegistryError, match="write a real hypothesis"):
        an_experiment(connection, hypothesis="it works")


def test_whitespace_is_not_a_hypothesis(connection: Connection) -> None:
    with pytest.raises(RegistryError, match="write a real hypothesis"):
        an_experiment(connection, hypothesis="              ")


def test_parameters_are_optional_but_stored_as_an_object(connection: Connection) -> None:
    experiment = an_experiment(connection, params=None)
    assert get_experiment(connection, experiment.experiment_id).params == {}


def test_every_kind_can_be_registered(connection: Connection) -> None:
    for kind in ExperimentKind:
        experiment = an_experiment(connection, kind=kind)
        assert get_experiment(connection, experiment.experiment_id).kind is kind


def test_an_unknown_experiment_is_refused(connection: Connection) -> None:
    with pytest.raises(RegistryError, match="register the question before measuring"):
        get_experiment(connection, 10**9)


# ---------------------------------------------------------------- results need one


def test_a_result_without_an_experiment_cannot_be_built() -> None:
    """The point of this step: the field has no default, so it cannot be left out."""
    values = a_result(1).model_dump()
    del values["experiment_id"]
    del values["created_at"]
    with pytest.raises(ValidationError, match="experiment_id"):
        AlphaResult(**values)


def test_a_result_naming_an_unregistered_experiment_is_refused(registry: Connection) -> None:
    with pytest.raises(RegistryError, match="experiment 999999 is not registered"):
        record_result(registry, a_result(999999))


def test_a_result_with_a_registered_experiment_is_stored(registry: Connection) -> None:
    experiment = an_experiment(registry)
    stored = record_result(registry, a_result(experiment.experiment_id))
    assert stored.experiment_id == experiment.experiment_id


def test_the_experiment_a_result_belongs_to_can_be_read_back(registry: Connection) -> None:
    experiment = an_experiment(registry)
    stored = record_result(registry, a_result(experiment.experiment_id))
    linked = record_result.__module__  # sanity: the module imported fine
    assert linked
    question = get_experiment(registry, stored.experiment_id)
    assert question.hypothesis == HYPOTHESIS


def test_results_cannot_be_added_to_a_finished_experiment(registry: Connection) -> None:
    """A finished experiment has already been written up; later runs need a new question."""
    experiment = an_experiment(registry)
    set_status(registry, experiment.experiment_id, ExperimentStatus.RUNNING)
    set_status(registry, experiment.experiment_id, ExperimentStatus.FINISHED)
    with pytest.raises(RegistryError, match="is finished"):
        record_result(registry, a_result(experiment.experiment_id))


def test_results_cannot_be_added_to_an_abandoned_experiment(registry: Connection) -> None:
    experiment = an_experiment(registry)
    set_status(registry, experiment.experiment_id, ExperimentStatus.ABANDONED)
    with pytest.raises(RegistryError, match="is abandoned"):
        record_result(registry, a_result(experiment.experiment_id))


def test_an_open_experiment_is_returned(registry: Connection) -> None:
    experiment = an_experiment(registry)
    assert require_open_experiment(registry, experiment.experiment_id).is_open is True


# ---------------------------------------------------------------- status moves


def test_the_normal_path_is_planned_running_finished(connection: Connection) -> None:
    experiment = an_experiment(connection)
    assert set_status(connection, experiment.experiment_id, ExperimentStatus.RUNNING).status is (
        ExperimentStatus.RUNNING
    )
    assert set_status(connection, experiment.experiment_id, ExperimentStatus.FINISHED).status is (
        ExperimentStatus.FINISHED
    )


def test_an_experiment_can_be_abandoned_at_any_point(connection: Connection) -> None:
    """Dropping an idea is information, so it is recorded rather than deleted."""
    planned = an_experiment(connection)
    set_status(connection, planned.experiment_id, ExperimentStatus.ABANDONED)

    started = an_experiment(connection)
    set_status(connection, started.experiment_id, ExperimentStatus.RUNNING)
    set_status(connection, started.experiment_id, ExperimentStatus.ABANDONED)


def test_a_finished_experiment_cannot_be_restarted(connection: Connection) -> None:
    experiment = an_experiment(connection)
    set_status(connection, experiment.experiment_id, ExperimentStatus.RUNNING)
    set_status(connection, experiment.experiment_id, ExperimentStatus.FINISHED)
    with pytest.raises(RegistryError, match="cannot go from finished to running"):
        set_status(connection, experiment.experiment_id, ExperimentStatus.RUNNING)


def test_an_experiment_cannot_skip_straight_to_finished(connection: Connection) -> None:
    experiment = an_experiment(connection)
    with pytest.raises(RegistryError, match="cannot go from planned to finished"):
        set_status(connection, experiment.experiment_id, ExperimentStatus.FINISHED)


# ---------------------------------------------------------------- listing


def test_experiments_can_be_listed_and_filtered(connection: Connection) -> None:
    an_experiment(connection, kind=ExperimentKind.ALPHA, author="abhishek")
    an_experiment(connection, kind=ExperimentKind.ML, author="anuj")

    by_kind = list_experiments(connection, kind=ExperimentKind.ML)
    assert all(e.kind is ExperimentKind.ML for e in by_kind)
    by_author = list_experiments(connection, author="anuj")
    assert all(e.author == "anuj" for e in by_author)
    planned = list_experiments(connection, status=ExperimentStatus.PLANNED)
    assert all(e.status is ExperimentStatus.PLANNED for e in planned)


def test_nothing_is_left_behind(connection: Connection) -> None:
    leaked = connection.execute(
        text("SELECT count(*) FROM experiments WHERE hypothesis = :h"), {"h": HYPOTHESIS}
    ).scalar_one()
    assert leaked == 0
