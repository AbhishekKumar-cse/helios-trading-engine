"""Tests for the TEST-period access log (step 067).

The rule under test: ADR-004 allows two uses of the TEST period per alpha version, and the
third attempt must fail. Everything runs inside a rolled-back transaction.
"""

from decimal import Decimal

import pytest
from registry_sql import GATE_CONFIG, SNAPSHOT
from sqlalchemy import Connection, text

from helios.common.project_config import HorizonFamily
from helios.registry.api import AlphaDefinition, Provenance, RegistryError, register_definition
from helios.registry.results import AlphaResult, Split, Status, list_results
from helios.registry.test_access import (
    MAX_TEST_ACCESSES,
    TestSetLimitReached,
    count_test_accesses,
    list_test_accesses,
    record_test_access,
    record_test_result,
    remaining_test_accesses,
)

COMMIT = "a" * 40
CONFIG_HASH = "b" * 64
SNAPSHOT_ID = "t-access-snapshot"
GATES_ID = "t_access_gates"
ALPHA = "t_access_alpha"
ALL_PASSED = {"G1": True, "G2": True, "G3": True, "G4": True, "G5": True, "G6": True}
PURPOSE = "final confirmation before promotion"


@pytest.fixture
def registry(connection: Connection) -> Connection:
    """Two versions of one alpha, a gate configuration and a data snapshot."""
    for version in (1, 2):
        register_definition(
            connection,
            AlphaDefinition(
                alpha_id=ALPHA,
                version=version,
                name="alpha used by the access tests",
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


def access(connection: Connection, version: int = 1, purpose: str = PURPOSE) -> object:
    return record_test_access(
        connection,
        alpha_id=ALPHA,
        version=version,
        snapshot_id=SNAPSHOT_ID,
        actor="abhishek",
        purpose=purpose,
    )


def a_result(**overrides: object) -> AlphaResult:
    values: dict[str, object] = {
        "alpha_id": ALPHA,
        "version": 1,
        "split": Split.TEST,
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


# ---------------------------------------------------------------- the limit


def test_the_first_two_accesses_are_allowed(registry: Connection) -> None:
    access(registry)
    access(registry)
    assert count_test_accesses(registry, ALPHA, 1) == MAX_TEST_ACCESSES


def test_the_third_access_is_refused(registry: Connection) -> None:
    """The rule this step exists for."""
    access(registry)
    access(registry)
    with pytest.raises(TestSetLimitReached, match="already used the TEST period 2 times"):
        access(registry)


def test_the_refusal_says_what_to_do_instead(registry: Connection) -> None:
    access(registry)
    access(registry)
    with pytest.raises(TestSetLimitReached) as failure:
        access(registry)
    message = str(failure.value)
    assert "validation period" in message
    assert "new version" in message


def test_nothing_is_written_when_the_limit_is_reached(registry: Connection) -> None:
    access(registry)
    access(registry)
    with pytest.raises(TestSetLimitReached):
        access(registry)
    assert count_test_accesses(registry, ALPHA, 1) == 2  # still two, not three


def test_remaining_counts_down(registry: Connection) -> None:
    assert remaining_test_accesses(registry, ALPHA, 1) == 2
    access(registry)
    assert remaining_test_accesses(registry, ALPHA, 1) == 1
    access(registry)
    assert remaining_test_accesses(registry, ALPHA, 1) == 0


def test_each_version_has_its_own_budget(registry: Connection) -> None:
    """A new version is a new idea, so it starts with two fresh accesses."""
    access(registry, version=1)
    access(registry, version=1)
    access(registry, version=2)  # must be allowed
    assert count_test_accesses(registry, ALPHA, 1) == 2
    assert count_test_accesses(registry, ALPHA, 2) == 1


def test_an_untouched_alpha_has_no_accesses(registry: Connection) -> None:
    assert count_test_accesses(registry, "t_never_tested", 1) == 0


# ---------------------------------------------------------------- what is written down


def test_the_access_records_who_when_and_why(registry: Connection) -> None:
    written = access(registry)
    logged = list_test_accesses(registry, ALPHA, 1)
    assert len(logged) == 1
    entry = logged[0]
    assert entry.actor == "abhishek"
    assert entry.purpose == PURPOSE
    assert entry.snapshot_id == SNAPSHOT_ID
    assert entry.access_id == written.access_id  # type: ignore[attr-defined]
    assert entry.accessed_at is not None


def test_a_vague_purpose_is_refused(registry: Connection) -> None:
    """An access with a stated reason is a decision; an unexplained one is a habit."""
    with pytest.raises(RegistryError, match="say why the TEST period is being used"):
        access(registry, purpose="because")


def test_whitespace_does_not_count_as_a_purpose(registry: Connection) -> None:
    with pytest.raises(RegistryError, match="say why"):
        access(registry, purpose="          ")


def test_accesses_are_listed_oldest_first(registry: Connection) -> None:
    access(registry, purpose="first confirmation run on the test period")
    access(registry, purpose="second confirmation after the data rebuild")
    purposes = [entry.purpose for entry in list_test_accesses(registry, ALPHA, 1)]
    assert purposes[0].startswith("first")


def test_listing_can_cover_every_alpha(registry: Connection) -> None:
    access(registry, version=1)
    access(registry, version=2)
    assert len(list_test_accesses(registry, ALPHA)) == 2


# ---------------------------------------------------------------- results on the TEST split


def test_a_test_result_logs_the_access_and_stores_the_result(registry: Connection) -> None:
    stored, logged = record_test_result(registry, a_result(), actor="abhishek", purpose=PURPOSE)
    assert stored.created_at is not None
    assert logged.run_id == stored.run_id  # the log points at the run it allowed
    assert count_test_accesses(registry, ALPHA, 1) == 1


def test_a_third_test_result_stores_nothing(registry: Connection) -> None:
    """The access is written before the result, so an over-limit run keeps neither."""
    record_test_result(registry, a_result(), actor="abhishek", purpose=PURPOSE)
    record_test_result(registry, a_result(), actor="abhishek", purpose=PURPOSE)
    before = len(list_results(registry, alpha_id=ALPHA))

    with pytest.raises(TestSetLimitReached):
        record_test_result(registry, a_result(), actor="abhishek", purpose=PURPOSE)

    assert len(list_results(registry, alpha_id=ALPHA)) == before
    assert count_test_accesses(registry, ALPHA, 1) == 2


def test_a_promoted_test_result_is_allowed_within_the_limit(registry: Connection) -> None:
    stored, _ = record_test_result(
        registry, a_result(status=Status.PROMOTED), actor="abhishek", purpose=PURPOSE
    )
    assert stored.status is Status.PROMOTED


def test_validation_results_do_not_go_through_this_path(registry: Connection) -> None:
    with pytest.raises(RegistryError, match="only for the TEST split"):
        record_test_result(registry, a_result(split=Split.VALID), actor="abhishek", purpose=PURPOSE)


def test_validation_runs_are_unlimited(registry: Connection) -> None:
    """Only the TEST period is rationed; tuning happens on validation."""
    from helios.registry.results import record_result

    for _ in range(5):
        record_result(registry, a_result(split=Split.VALID))
    assert count_test_accesses(registry, ALPHA, 1) == 0


def test_nothing_is_left_behind(connection: Connection) -> None:
    leaked = connection.execute(
        text("SELECT count(*) FROM test_set_access WHERE alpha_id LIKE 't\\_%'")
    ).scalar_one()
    assert leaked == 0
