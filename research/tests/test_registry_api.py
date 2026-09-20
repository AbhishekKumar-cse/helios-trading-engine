"""Tests for the registry API (step 064).

They run against the real PostgreSQL inside a transaction that is rolled back, and skip when
no database is reachable. Alpha ids are prefixed `t_` so they never collide with real work.
"""

import pytest
from pydantic import ValidationError
from sqlalchemy import Connection, text

from helios.common.project_config import HorizonFamily
from helios.registry.api import (
    AlphaDefinition,
    Provenance,
    RegistryError,
    count_versions,
    get_alpha,
    list_alphas,
    next_version,
    register_definition,
)

COMMIT = "a" * 40


def definition(
    alpha_id: str = "t_momentum", version: int = 1, **overrides: object
) -> AlphaDefinition:
    values: dict[str, object] = {
        "alpha_id": alpha_id,
        "version": version,
        "name": "hourly momentum on BTC",
        "provenance": Provenance.HUMAN,
        "spec": {"feature": "log_return_24h", "rule": "sign", "cap": 1.0},
        "feature_set_version": "v1",
        "horizon_family": HorizonFamily.HOURLY,
        "horizon_periods": 1,
        "author": "abhishek",
        "code_commit": COMMIT,
    }
    return AlphaDefinition(**(values | overrides))


# ---------------------------------------------------------------- checks before the database


def test_a_bad_alpha_id_is_caught_early() -> None:
    """The model explains the rule; the database would only say 'check violation'."""
    for bad in ("Momentum", "9lives", "x", "has spaces", "trailing-dash"):
        with pytest.raises(ValidationError, match="alpha_id"):
            definition(alpha_id=bad)


def test_a_short_commit_is_caught_early() -> None:
    with pytest.raises(ValidationError, match="40-character git commit"):
        definition(code_commit="abc123")


def test_an_unknown_provenance_is_caught_early() -> None:
    with pytest.raises(ValidationError):
        definition(provenance="guesswork")


def test_an_unknown_horizon_family_is_caught_early() -> None:
    with pytest.raises(ValidationError):
        definition(horizon_family="H-DAILY")


def test_an_empty_spec_is_caught_early() -> None:
    with pytest.raises(ValidationError):
        definition(spec={})


def test_a_definition_cannot_be_changed_after_it_is_made() -> None:
    """Frozen: the object in memory behaves like the row in the database."""
    idea = definition()
    with pytest.raises(ValidationError):
        idea.horizon_periods = 24  # type: ignore[misc]


def test_the_commit_is_recorded_automatically() -> None:
    values = definition().model_dump()
    del values["code_commit"]
    del values["created_at"]
    assert len(AlphaDefinition(**values).code_commit) == 40


# ---------------------------------------------------------------- registering


def test_a_definition_is_stored_and_returned(connection: Connection) -> None:
    stored = register_definition(connection, definition())
    assert stored.created_at is not None  # filled in by the database
    assert stored.alpha_id == "t_momentum"


def test_the_same_version_twice_is_refused(connection: Connection) -> None:
    register_definition(connection, definition())
    with pytest.raises(RegistryError, match="already registered"):
        register_definition(connection, definition())


def test_the_message_says_what_to_do_instead(connection: Connection) -> None:
    register_definition(connection, definition())
    with pytest.raises(RegistryError) as failure:
        register_definition(connection, definition())
    assert "new version" in str(failure.value)


def test_a_new_version_is_accepted(connection: Connection) -> None:
    register_definition(connection, definition(version=1))
    register_definition(connection, definition(version=2, horizon_periods=24))
    assert count_versions(connection, "t_momentum") == 2


def test_next_version_counts_up(connection: Connection) -> None:
    assert next_version(connection, "t_new_idea") == 1
    register_definition(connection, definition(alpha_id="t_new_idea"))
    assert next_version(connection, "t_new_idea") == 2


def test_the_spec_survives_the_round_trip(connection: Connection) -> None:
    spec = {"feature": "log_return_4h", "threshold": 0.002, "levels": [1, 2, 3]}
    register_definition(connection, definition(alpha_id="t_spec", spec=spec))
    assert get_alpha(connection, "t_spec").spec == spec


# ---------------------------------------------------------------- reading


def test_get_alpha_returns_the_newest_version(connection: Connection) -> None:
    register_definition(connection, definition(version=1, horizon_periods=1))
    register_definition(connection, definition(version=2, horizon_periods=24))
    newest = get_alpha(connection, "t_momentum")
    assert (newest.version, newest.horizon_periods) == (2, 24)


def test_an_older_version_can_still_be_read(connection: Connection) -> None:
    register_definition(connection, definition(version=1, horizon_periods=1))
    register_definition(connection, definition(version=2, horizon_periods=24))
    assert get_alpha(connection, "t_momentum", version=1).horizon_periods == 1


def test_an_unknown_alpha_is_refused(connection: Connection) -> None:
    with pytest.raises(RegistryError, match="t_ghost is not registered"):
        get_alpha(connection, "t_ghost")


def test_an_unknown_version_is_refused(connection: Connection) -> None:
    register_definition(connection, definition())
    with pytest.raises(RegistryError, match="version 9 is not registered"):
        get_alpha(connection, "t_momentum", version=9)


def test_types_come_back_as_types(connection: Connection) -> None:
    register_definition(connection, definition())
    loaded = get_alpha(connection, "t_momentum")
    assert loaded.horizon_family is HorizonFamily.HOURLY
    assert loaded.provenance is Provenance.HUMAN
    assert isinstance(loaded.spec, dict)


# ---------------------------------------------------------------- listing


def test_listing_shows_one_row_per_alpha(connection: Connection) -> None:
    before = len(list_alphas(connection))
    register_definition(connection, definition(alpha_id="t_one", version=1))
    register_definition(connection, definition(alpha_id="t_one", version=2))
    register_definition(connection, definition(alpha_id="t_two"))
    listed = list_alphas(connection)
    assert len(listed) == before + 2
    assert {"t_one", "t_two"} <= set(a.alpha_id for a in listed)
    assert next(a.version for a in listed if a.alpha_id == "t_one") == 2


def test_the_whole_history_can_be_listed(connection: Connection) -> None:
    register_definition(connection, definition(alpha_id="t_one", version=1))
    register_definition(connection, definition(alpha_id="t_one", version=2))
    versions = [
        a.version for a in list_alphas(connection, latest_only=False) if a.alpha_id == "t_one"
    ]
    assert sorted(versions) == [1, 2]


def test_listing_can_be_filtered_by_author(connection: Connection) -> None:
    register_definition(connection, definition(alpha_id="t_mine", author="abhishek"))
    register_definition(connection, definition(alpha_id="t_theirs", author="anuj"))
    ids = [a.alpha_id for a in list_alphas(connection, author="anuj")]
    assert "t_theirs" in ids
    assert "t_mine" not in ids


def test_listing_can_be_filtered_by_horizon_family(connection: Connection) -> None:
    register_definition(
        connection, definition(alpha_id="t_fast", horizon_family=HorizonFamily.MINUTE)
    )
    register_definition(
        connection, definition(alpha_id="t_slow", horizon_family=HorizonFamily.HOURLY)
    )
    ids = [a.alpha_id for a in list_alphas(connection, horizon_family=HorizonFamily.MINUTE)]
    assert "t_fast" in ids
    assert "t_slow" not in ids


def test_nothing_is_left_behind(connection: Connection) -> None:
    """Sanity: the rows above live only inside the rolled-back transaction."""
    leaked = connection.execute(
        text("SELECT count(*) FROM alpha_definitions WHERE alpha_id LIKE 't\\_%'")
    ).scalar_one()
    assert leaked == 0
