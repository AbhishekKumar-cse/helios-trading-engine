"""The registry refuses to be rewritten (step 062).

These tests try to do the things a careless or dishonest edit would do — improve a Sharpe
ratio, delete an inconvenient run, change what an idea was — and check that PostgreSQL
refuses each one. Everything runs inside a transaction that is rolled back.
"""

import pytest
from registry_sql import ACCESS, COMMIT, DEFINITION, GATE_CONFIG, HASH, RESULT, SNAPSHOT
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

INSERT_ONLY = "is insert-only"


@pytest.fixture
def registry(connection: Connection) -> Connection:
    """One definition, one gate config, one snapshot and one saved result."""
    connection.execute(
        text(DEFINITION),
        {
            "alpha_id": "locked_alpha",
            "version": 1,
            "provenance": "human",
            "family": "H-HOURLY",
            "horizon": 1,
            "commit": COMMIT,
        },
    )
    connection.execute(
        text(GATE_CONFIG),
        {
            "config_id": "locked_gates",
            "turnover_min": 0.01,
            "turnover_max": 0.70,
            "stress": 2.0,
            "hash": HASH,
        },
    )
    connection.execute(text(SNAPSHOT), {"id": "locked-snapshot", "commit": COMMIT})
    connection.execute(
        text(RESULT),
        {
            "run_id": "locked-run",
            "alpha_id": "locked_alpha",
            "version": 1,
            "split": "valid",
            "snapshot_id": "locked-snapshot",
            "config_id": "locked_gates",
            "sharpe": "0.4",
            "turnover": "0.3",
            "drawdown": "-0.2",
            "hit_rate": "0.48",
            "periods": 8760,
            "status": "EVALUATED",
            "commit": COMMIT,
            "hash": HASH,
        },
    )
    return connection


# ---------------------------------------------------------------- results


def test_a_disappointing_sharpe_cannot_be_improved(registry: Connection) -> None:
    """The reason this step exists."""
    with pytest.raises(IntegrityError, match=INSERT_ONLY):
        registry.execute(text("UPDATE alpha_results SET sharpe = 2.5 WHERE run_id = 'locked-run'"))


def test_a_result_cannot_be_deleted(registry: Connection) -> None:
    with pytest.raises(IntegrityError, match=INSERT_ONLY):
        registry.execute(text("DELETE FROM alpha_results WHERE run_id = 'locked-run'"))


def test_a_status_cannot_be_flipped_to_promoted(registry: Connection) -> None:
    """A promotion is a new row, not a rewrite of the run that failed."""
    with pytest.raises(IntegrityError, match=INSERT_ONLY):
        registry.execute(
            text("UPDATE alpha_results SET status = 'PROMOTED' WHERE run_id = 'locked-run'")
        )


def test_the_dirty_flag_cannot_be_cleared(registry: Connection) -> None:
    with pytest.raises(IntegrityError, match=INSERT_ONLY):
        registry.execute(text("UPDATE alpha_results SET dirty = false"))


def test_updating_nothing_is_still_refused(registry: Connection) -> None:
    """Even a no-op edit is refused, so nobody can argue about what 'changed' means."""
    with pytest.raises(IntegrityError, match=INSERT_ONLY):
        registry.execute(
            text("UPDATE alpha_results SET sharpe = sharpe WHERE run_id = 'locked-run'")
        )


def test_a_bulk_delete_is_refused(registry: Connection) -> None:
    with pytest.raises(IntegrityError, match=INSERT_ONLY):
        registry.execute(text("DELETE FROM alpha_results"))


def test_the_error_says_what_to_do_instead(registry: Connection) -> None:
    with pytest.raises(IntegrityError) as failure:
        registry.execute(text("DELETE FROM alpha_results WHERE run_id = 'locked-run'"))
    message = str(failure.value)
    assert "alpha_results" in message
    assert "DELETE" in message
    assert "inserting a new row" in message


# ---------------------------------------------------------------- definitions


def test_a_definition_cannot_be_rewritten(registry: Connection) -> None:
    with pytest.raises(IntegrityError, match=INSERT_ONLY):
        registry.execute(
            text(
                'UPDATE alpha_definitions SET spec_json = \'{"rule": "changed"}\'::jsonb '
                "WHERE alpha_id = 'locked_alpha'"
            )
        )


def test_a_definition_cannot_be_deleted(registry: Connection) -> None:
    with pytest.raises(IntegrityError, match=INSERT_ONLY):
        registry.execute(text("DELETE FROM alpha_definitions WHERE alpha_id = 'locked_alpha'"))


# ---------------------------------------------------------------- snapshots


def test_a_snapshot_cannot_be_rewritten(registry: Connection) -> None:
    """Changing a snapshot would make a result point at data it never used."""
    with pytest.raises(IntegrityError, match=INSERT_ONLY):
        registry.execute(
            text("UPDATE data_snapshots SET row_count = 1 WHERE snapshot_id = 'locked-snapshot'")
        )


def test_a_snapshot_cannot_be_deleted(registry: Connection) -> None:
    with pytest.raises(IntegrityError, match=INSERT_ONLY):
        registry.execute(text("DELETE FROM data_snapshots WHERE snapshot_id = 'locked-snapshot'"))


# ---------------------------------------------------------------- what still works


def test_new_rows_are_still_accepted(registry: Connection) -> None:
    """History grows; it never changes."""
    registry.execute(
        text(RESULT),
        {
            "run_id": "second-run",
            "alpha_id": "locked_alpha",
            "version": 1,
            "split": "test",
            "snapshot_id": "locked-snapshot",
            "config_id": "locked_gates",
            "sharpe": "1.8",
            "turnover": "0.3",
            "drawdown": "-0.1",
            "hit_rate": "0.55",
            "periods": 8760,
            "status": "PROMOTED",
            "commit": COMMIT,
            "hash": HASH,
        },
    )
    runs = registry.execute(
        text("SELECT count(*) FROM alpha_results WHERE alpha_id = 'locked_alpha'")
    ).scalar_one()
    assert runs == 2  # the weak run is still there next to the promoted one


def test_a_new_version_of_an_idea_is_still_allowed(registry: Connection) -> None:
    registry.execute(
        text(DEFINITION),
        {
            "alpha_id": "locked_alpha",
            "version": 2,
            "provenance": "human",
            "family": "H-HOURLY",
            "horizon": 4,
            "commit": COMMIT,
        },
    )
    versions = registry.execute(
        text("SELECT count(*) FROM alpha_definitions WHERE alpha_id = 'locked_alpha'")
    ).scalar_one()
    assert versions == 2


def test_tables_that_are_meant_to_change_still_can(registry: Connection) -> None:
    """Only the record of what happened is frozen; reference data is not."""
    registry.execute(text("UPDATE instruments SET active = active"))
    registry.execute(text("UPDATE experiments SET status = 'running' WHERE status = 'planned'"))


def test_the_access_log_can_still_be_appended(registry: Connection) -> None:
    registry.execute(
        text(ACCESS),
        {
            "alpha_id": "locked_alpha",
            "version": 1,
            "snapshot_id": "locked-snapshot",
            "purpose": "first confirmation run on the test period",
        },
    )
    used = registry.execute(
        text("SELECT count(*) FROM test_set_access WHERE alpha_id = 'locked_alpha'")
    ).scalar_one()
    assert used == 1


def test_the_triggers_are_installed(connection: Connection) -> None:
    names = connection.execute(
        text(
            "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal "
            "AND tgname LIKE '%_is_insert_only' ORDER BY tgname"
        )
    ).scalars()
    assert list(names) == [
        "alpha_definitions_is_insert_only",
        "alpha_results_is_insert_only",
        "data_snapshots_is_insert_only",
    ]
