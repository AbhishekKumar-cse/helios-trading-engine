"""The rules of the alpha registry, enforced by the database (step 061).

Every test runs inside a transaction that is rolled back, and skips when PostgreSQL is not
reachable. Ids are deliberately fake so nothing collides with real work.
"""

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from helios.common import db

COMMIT = "a" * 40
HASH = "b" * 64

DEFINITION = """
INSERT INTO alpha_definitions
    (alpha_id, version, name, provenance, spec_json, feature_set_version,
     horizon_family, horizon_periods, author, code_commit)
VALUES (:alpha_id, :version, 'test alpha', :provenance, '{"rule": "momentum"}'::jsonb, 'fs_v1',
        :family, :horizon, 'abhishek', :commit)
"""

GATE_CONFIG = """
INSERT INTO alpha_gate_config
    (config_id, sharpe_min, fitness_min, fitness_turnover_floor, turnover_min, turnover_max,
     stability_min_positive_fraction, cost_stress_multiplier, cost_stress_sharpe_min,
     config_hash, author, effective_from)
VALUES (:config_id, 1.0, 1.0, 0.125, :turnover_min, :turnover_max, 0.5, :stress, 0.0,
        :hash, 'abhishek', now())
"""

SNAPSHOT = """
INSERT INTO data_snapshots
    (snapshot_id, source, interval, symbols, first_open_time, last_open_time,
     file_count, row_count, total_bytes, code_commit)
VALUES (:id, 'test', '1h', '["TESTAUSDT"]'::jsonb, 1, 2, 1, 10, 100, :commit)
"""

RESULT = """
INSERT INTO alpha_results
    (run_id, alpha_id, version, split, snapshot_id, gate_config_id,
     sharpe, annual_return, turnover, fitness, max_drawdown, hit_rate,
     periods, gate_results, status, code_commit, config_hash, seed, dirty)
VALUES (:run_id, :alpha_id, :version, :split, :snapshot_id, :config_id,
        :sharpe, 0.25, :turnover, 1.4, :drawdown, :hit_rate,
        :periods, '{"G1": true}'::jsonb, :status, :commit, :hash, 0, false)
"""

ACCESS = """
INSERT INTO test_set_access (alpha_id, version, snapshot_id, actor, purpose)
VALUES (:alpha_id, :version, :snapshot_id, 'abhishek', :purpose)
"""


@pytest.fixture
def connection() -> Iterator[Connection]:
    try:
        db.get_settings()
    except ValidationError:
        pytest.skip("database settings not configured (no .env / POSTGRES_* variables)")
    try:
        conn = db.get_engine().connect()
    except Exception as exc:  # noqa: BLE001 - any failure here means "no database"
        pytest.skip(f"database not reachable: {type(exc).__name__}")
    transaction = conn.begin()
    try:
        yield conn
    finally:
        transaction.rollback()
        conn.close()


@pytest.fixture
def registry(connection: Connection) -> Connection:
    """One alpha definition, one gate config and one data snapshot to point at."""
    connection.execute(
        text(DEFINITION),
        {
            "alpha_id": "test_alpha",
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
            "config_id": "test_gates_v1",
            "turnover_min": 0.01,
            "turnover_max": 0.70,
            "stress": 2.0,
            "hash": HASH,
        },
    )
    connection.execute(text(SNAPSHOT), {"id": "test-snapshot", "commit": COMMIT})
    return connection


def insert_result(connection: Connection, **overrides: object) -> None:
    params: dict[str, object] = {
        "run_id": "run-1",
        "alpha_id": "test_alpha",
        "version": 1,
        "split": "valid",
        "snapshot_id": "test-snapshot",
        "config_id": "test_gates_v1",
        "sharpe": 1.5,
        "turnover": 0.3,
        "drawdown": -0.2,
        "hit_rate": 0.55,
        "periods": 8760,
        "status": "EVALUATED",
        "commit": COMMIT,
        "hash": HASH,
    }
    connection.execute(text(RESULT), params | overrides)


def test_the_four_tables_exist(connection: Connection) -> None:
    found = connection.execute(
        text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
    ).scalars()
    assert {
        "alpha_definitions",
        "alpha_results",
        "alpha_gate_config",
        "test_set_access",
    } <= set(found)


# ---------------------------------------------------------------- definitions


def test_a_definition_is_accepted(registry: Connection) -> None:
    count = registry.execute(
        text("SELECT count(*) FROM alpha_definitions WHERE alpha_id = 'test_alpha'")
    ).scalar_one()
    assert count == 1


def test_the_same_version_cannot_be_added_twice(registry: Connection) -> None:
    """A change to an idea is a new version, never a second row for the same one."""
    with pytest.raises(IntegrityError, match="alpha_definitions_pkey"):
        registry.execute(
            text(DEFINITION),
            {
                "alpha_id": "test_alpha",
                "version": 1,
                "provenance": "human",
                "family": "H-HOURLY",
                "horizon": 1,
                "commit": COMMIT,
            },
        )


def test_a_second_version_is_fine(registry: Connection) -> None:
    registry.execute(
        text(DEFINITION),
        {
            "alpha_id": "test_alpha",
            "version": 2,
            "provenance": "ml",
            "family": "H-MINUTE",
            "horizon": 60,
            "commit": COMMIT,
        },
    )
    versions = registry.execute(
        text("SELECT count(*) FROM alpha_definitions WHERE alpha_id = 'test_alpha'")
    ).scalar_one()
    assert versions == 2


@pytest.mark.parametrize(
    ("field", "value", "constraint"),
    [
        ("family", "H-DAILY", "alpha_definitions_family_known"),
        ("provenance", "guesswork", "alpha_definitions_provenance_known"),
        ("horizon", 0, "alpha_definitions_horizon_positive"),
        ("commit", "short", "alpha_definitions_commit_full"),
    ],
)
def test_bad_definitions_are_refused(
    connection: Connection, field: str, value: object, constraint: str
) -> None:
    params: dict[str, object] = {
        "alpha_id": "bad_alpha",
        "version": 1,
        "provenance": "human",
        "family": "H-HOURLY",
        "horizon": 1,
        "commit": COMMIT,
    }
    with pytest.raises(IntegrityError, match=constraint):
        connection.execute(text(DEFINITION), params | {field: value})


# ---------------------------------------------------------------- gate configuration


def test_gate_thresholds_are_stored(registry: Connection) -> None:
    row = registry.execute(
        text(
            "SELECT sharpe_min, fitness_turnover_floor, turnover_max "
            "FROM alpha_gate_config WHERE config_id = 'test_gates_v1'"
        )
    ).one()
    assert float(row.sharpe_min) == 1.0
    assert float(row.fitness_turnover_floor) == 0.125  # ADR-002
    assert float(row.turnover_max) == 0.70


def test_a_backwards_turnover_range_is_refused(connection: Connection) -> None:
    with pytest.raises(IntegrityError, match="alpha_gate_config_turnover_range"):
        connection.execute(
            text(GATE_CONFIG),
            {
                "config_id": "bad_gates",
                "turnover_min": 0.9,
                "turnover_max": 0.1,
                "stress": 2.0,
                "hash": HASH,
            },
        )


def test_a_cost_stress_below_one_is_refused(connection: Connection) -> None:
    """Stressing at less than 1x cost would make the gate easier, not harder."""
    with pytest.raises(IntegrityError, match="alpha_gate_config_stress_at_least_1"):
        connection.execute(
            text(GATE_CONFIG),
            {
                "config_id": "bad_gates",
                "turnover_min": 0.01,
                "turnover_max": 0.7,
                "stress": 0.5,
                "hash": HASH,
            },
        )


# ---------------------------------------------------------------- results


def test_a_result_is_accepted(registry: Connection) -> None:
    insert_result(registry)
    row = registry.execute(
        text("SELECT sharpe, status, split, dirty FROM alpha_results WHERE run_id = 'run-1'")
    ).one()
    assert float(row.sharpe) == 1.5
    assert (row.status, row.split, row.dirty) == ("EVALUATED", "valid", False)


def test_a_result_must_point_at_a_real_definition(registry: Connection) -> None:
    with pytest.raises(IntegrityError, match="alpha_results_definition_fkey"):
        insert_result(registry, alpha_id="no_such_alpha")


def test_a_result_must_point_at_a_real_snapshot(registry: Connection) -> None:
    with pytest.raises(IntegrityError, match="snapshot"):
        insert_result(registry, snapshot_id="no-such-snapshot")


def test_a_used_definition_cannot_be_deleted(registry: Connection) -> None:
    insert_result(registry)
    with pytest.raises(IntegrityError, match="alpha_results_definition_fkey"):
        registry.execute(text("DELETE FROM alpha_definitions WHERE alpha_id = 'test_alpha'"))


@pytest.mark.parametrize(
    ("field", "value", "constraint"),
    [
        ("split", "holdout", "alpha_results_split_known"),
        ("status", "AMAZING", "alpha_results_status_known"),
        ("turnover", -0.1, "alpha_results_turnover_not_negative"),
        ("periods", 0, "alpha_results_periods_positive"),
        ("hit_rate", 1.5, "alpha_results_hit_rate_fraction"),
        ("drawdown", 0.3, "alpha_results_drawdown_not_positive"),
    ],
)
def test_bad_results_are_refused(
    registry: Connection, field: str, value: object, constraint: str
) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        insert_result(registry, **{field: value})


def test_an_alpha_cannot_be_promoted_on_training_data(registry: Connection) -> None:
    """Gate G4: a promotion must never rest on the data the idea was built on."""
    with pytest.raises(IntegrityError, match="alpha_results_no_promotion_on_train"):
        insert_result(registry, split="train", status="PROMOTED")


def test_training_results_may_still_be_recorded(registry: Connection) -> None:
    insert_result(registry, run_id="run-train", split="train", status="EVALUATED")
    count = registry.execute(
        text("SELECT count(*) FROM alpha_results WHERE run_id = 'run-train'")
    ).scalar_one()
    assert count == 1


def test_metrics_keep_their_exact_decimals(registry: Connection) -> None:
    insert_result(registry, sharpe="1.2345678901")
    sharpe = registry.execute(
        text("SELECT sharpe FROM alpha_results WHERE run_id = 'run-1'")
    ).scalar_one()
    assert str(sharpe) == "1.2345678901"


# ---------------------------------------------------------------- test-set access log


def test_an_access_is_logged(registry: Connection) -> None:
    registry.execute(
        text(ACCESS),
        {
            "alpha_id": "test_alpha",
            "version": 1,
            "snapshot_id": "test-snapshot",
            "purpose": "final confirmation before promotion",
        },
    )
    row = registry.execute(
        text(
            "SELECT actor, purpose, accessed_at FROM test_set_access WHERE alpha_id = 'test_alpha'"
        )
    ).one()
    assert row.actor == "abhishek"
    assert row.accessed_at <= datetime.now(UTC)


def test_an_empty_purpose_is_refused(registry: Connection) -> None:
    """ADR-004 allows two TEST uses per alpha; each one has to say why."""
    with pytest.raises(IntegrityError, match="test_set_access_purpose_not_empty"):
        registry.execute(
            text(ACCESS),
            {
                "alpha_id": "test_alpha",
                "version": 1,
                "snapshot_id": "test-snapshot",
                "purpose": "because",
            },
        )


def test_accesses_can_be_counted_per_alpha(registry: Connection) -> None:
    for purpose in ("first confirmation run", "second confirmation run"):
        registry.execute(
            text(ACCESS),
            {
                "alpha_id": "test_alpha",
                "version": 1,
                "snapshot_id": "test-snapshot",
                "purpose": purpose,
            },
        )
    used = registry.execute(
        text("SELECT count(*) FROM test_set_access WHERE alpha_id = 'test_alpha' AND version = 1")
    ).scalar_one()
    assert used == 2  # the limit from ADR-004


def test_an_access_must_name_a_real_alpha(registry: Connection) -> None:
    with pytest.raises(IntegrityError, match="test_set_access_definition_fkey"):
        registry.execute(
            text(ACCESS),
            {
                "alpha_id": "ghost_alpha",
                "version": 1,
                "snapshot_id": "test-snapshot",
                "purpose": "trying to sneak a look",
            },
        )
