"""Tests for storing gate thresholds (step 069).

The rule: the settings file and the database row must never drift apart, and a changed gate
is a new version.

These tests store the real thresholds under **their own version id** (`gates_t_v1`). The real
`gates_v1` row is loaded into the database by `scripts/load_gates.py`, and a test must never
depend on whether that has happened yet. One test checks the real row and skips if it is not
there. Everything runs inside a rolled-back transaction.
"""

from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Connection, text

from helios.common.config import ConfigError, config_hash
from helios.common.project_config import CONFIG_DIR, load_gates
from helios.registry.api import RegistryError
from helios.registry.gates import (
    GateConfigMismatch,
    StoredGateConfig,
    check_matches_file,
    find_gate_config,
    get_gate_config,
    list_gate_configs,
    load_gate_config_file,
)

REAL_FILE = CONFIG_DIR / "gates_v1.yaml"
TEST_VERSION = "gates_t_v1"


def a_gates_file(tmp_path: Path, old: str = "", new: str = "", version: str = TEST_VERSION) -> Path:
    """A copy of the real thresholds under our own version, optionally with one value changed."""
    content = REAL_FILE.read_text(encoding="utf-8")
    if old:
        content = content.replace(old, new)
    content = content.replace("version: gates_v1", f"version: {version}")
    path = tmp_path / f"{version}.yaml"
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def gates_file(tmp_path: Path) -> Path:
    return a_gates_file(tmp_path)


def store(connection: Connection, path: Path) -> tuple[StoredGateConfig, bool]:
    return load_gate_config_file(connection, path, author="abhishek")


# ---------------------------------------------------------------- storing


def test_a_gates_file_is_stored(connection: Connection, gates_file: Path) -> None:
    stored, is_new = store(connection, gates_file)
    assert is_new is True
    assert stored.config_id == TEST_VERSION


def test_the_stored_values_match_the_file(connection: Connection, gates_file: Path) -> None:
    stored, _ = store(connection, gates_file)
    config = load_gates(gates_file)
    assert stored.sharpe_min == Decimal("1.0")
    assert stored.fitness_turnover_floor == Decimal("0.125")  # ADR-002
    assert stored.turnover_min == Decimal(str(config.turnover_min))
    assert stored.turnover_max == Decimal(str(config.turnover_max))
    assert stored.require_out_of_sample is True
    assert stored.cost_stress_multiplier == Decimal("2.0")


def test_the_fingerprint_is_the_one_of_the_file(connection: Connection, gates_file: Path) -> None:
    """This is what ties the row to the file it came from."""
    stored, _ = store(connection, gates_file)
    assert stored.config_hash == config_hash(load_gates(gates_file))
    assert len(stored.config_hash) == 64


def test_the_sub_period_is_kept_in_extra(connection: Connection, gates_file: Path) -> None:
    """`stability_subperiod` has no column of its own, so it is stored beside the numbers."""
    stored, _ = store(connection, gates_file)
    assert stored.extra == {"stability_subperiod": "month"}


def test_the_row_can_be_read_back(connection: Connection, gates_file: Path) -> None:
    store(connection, gates_file)
    assert get_gate_config(connection, TEST_VERSION).config_id == TEST_VERSION


# ---------------------------------------------------------------- loading twice


def test_loading_the_same_file_again_changes_nothing(
    connection: Connection, gates_file: Path
) -> None:
    first, was_new = store(connection, gates_file)
    second, was_new_again = store(connection, gates_file)
    assert (was_new, was_new_again) == (True, False)
    assert first.config_hash == second.config_hash
    count = connection.execute(
        text("SELECT count(*) FROM alpha_gate_config WHERE config_id = :id"),
        {"id": TEST_VERSION},
    ).scalar_one()
    assert count == 1


def test_changed_values_under_the_same_version_are_refused(
    connection: Connection, tmp_path: Path
) -> None:
    """The reason this step exists: results judged by a version must keep their meaning."""
    store(connection, a_gates_file(tmp_path))
    easier = a_gates_file(tmp_path, "sharpe_min: 1.0", "sharpe_min: 0.2")
    with pytest.raises(GateConfigMismatch, match="already stored with a different fingerprint"):
        store(connection, easier)


def test_the_refusal_says_what_to_do(connection: Connection, tmp_path: Path) -> None:
    store(connection, a_gates_file(tmp_path))
    easier = a_gates_file(tmp_path, "sharpe_min: 1.0", "sharpe_min: 0.2")
    with pytest.raises(GateConfigMismatch) as failure:
        store(connection, easier)
    message = str(failure.value)
    assert "gates_v2.yaml" in message
    assert "ADR" in message


def test_a_new_version_is_stored_beside_the_old_one(connection: Connection, tmp_path: Path) -> None:
    store(connection, a_gates_file(tmp_path))
    stricter = a_gates_file(tmp_path, "sharpe_min: 1.0", "sharpe_min: 1.5", "gates_t_v2")
    stored, is_new = store(connection, stricter)
    assert (stored.config_id, is_new) == ("gates_t_v2", True)
    versions = {c.config_id for c in list_gate_configs(connection)}
    assert {TEST_VERSION, "gates_t_v2"} <= versions


# ---------------------------------------------------------------- checking for drift


def test_a_stored_version_matches_its_file(connection: Connection, gates_file: Path) -> None:
    store(connection, gates_file)
    assert check_matches_file(connection, TEST_VERSION, gates_file) is True


def test_drift_is_detected(connection: Connection, tmp_path: Path) -> None:
    """If someone edits the file without making a new version, this is how we find out."""
    store(connection, a_gates_file(tmp_path))
    changed = a_gates_file(tmp_path, "turnover_max: 0.70", "turnover_max: 0.90")
    assert check_matches_file(connection, TEST_VERSION, changed) is False


def test_the_real_gates_are_in_the_database(connection: Connection) -> None:
    """The step itself: configs/gates_v1.yaml is stored and still matches the file."""
    if find_gate_config(connection, "gates_v1") is None:
        pytest.skip("gates_v1 not loaded yet (run scripts/load_gates.py)")
    assert check_matches_file(connection, "gates_v1", REAL_FILE) is True


def test_an_unstored_version_is_refused(connection: Connection) -> None:
    with pytest.raises(RegistryError, match="run scripts/load_gates.py"):
        get_gate_config(connection, "gates_t_v99")


def test_find_returns_nothing_instead_of_raising(connection: Connection) -> None:
    assert find_gate_config(connection, "gates_t_v99") is None


# ---------------------------------------------------------------- impossible thresholds


def test_a_backwards_turnover_range_never_reaches_the_database(
    connection: Connection, tmp_path: Path
) -> None:
    """The settings model catches it while reading the file, before any SQL runs."""
    with pytest.raises(ConfigError, match="turnover_min must be smaller"):
        store(
            connection,
            a_gates_file(tmp_path, "turnover_min: 0.01", "turnover_min: 0.95", "gates_t_bad"),
        )


def test_results_can_point_at_the_stored_gates(connection: Connection, gates_file: Path) -> None:
    """A result names the gate version it was judged by; that row must exist."""
    stored, _ = store(connection, gates_file)
    exists = connection.execute(
        text("SELECT count(*) FROM alpha_gate_config WHERE config_id = :id"),
        {"id": stored.config_id},
    ).scalar_one()
    assert exists == 1


def test_nothing_is_left_behind(connection: Connection) -> None:
    leaked = connection.execute(
        text(r"SELECT count(*) FROM alpha_gate_config WHERE config_id LIKE 'gates\_t\_%'")
    ).scalar_one()
    assert leaked == 0
