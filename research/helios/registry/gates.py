"""Putting the gate thresholds in the database, with their fingerprint (step 069).

`configs/gates_v1.yaml` is what researchers read; `alpha_gate_config` is what results point
at. If those two ever disagreed, an old result would appear to have been judged by
thresholds it never met. The fingerprint (sha256 of the settings, step 027) ties them
together: the row stores the hash of the exact file it came from.

The rule this module enforces:

- loading the same file again is **harmless** — same id, same fingerprint, nothing changes;
- loading **different** values under the same id is **refused**. A changed gate is a new
  version (`gates_v2.yaml`), because results already judged by version 1 must keep meaning
  what they meant.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection, text

from helios.common.config import config_hash
from helios.common.project_config import CONFIG_DIR, GatesConfig, load_gates
from helios.registry.api import RegistryError

DEFAULT_GATES_FILE = CONFIG_DIR / "gates_v1.yaml"


class GateConfigMismatch(RegistryError):
    """Raised when a gate version is already stored with different values."""


class StoredGateConfig(BaseModel):
    """One gate configuration as the database holds it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    config_id: str
    sharpe_min: Decimal
    fitness_min: Decimal
    fitness_turnover_floor: Decimal
    turnover_min: Decimal
    turnover_max: Decimal
    require_out_of_sample: bool
    stability_min_positive_fraction: Decimal
    cost_stress_multiplier: Decimal
    cost_stress_sharpe_min: Decimal
    extra: dict[str, Any] | None
    config_hash: str
    author: str
    effective_from: datetime
    created_at: datetime | None = None


INSERT = text("""
INSERT INTO alpha_gate_config
    (config_id, sharpe_min, fitness_min, fitness_turnover_floor, turnover_min, turnover_max,
     require_out_of_sample, stability_min_positive_fraction, cost_stress_multiplier,
     cost_stress_sharpe_min, extra, config_hash, author, effective_from)
VALUES
    (:config_id, :sharpe_min, :fitness_min, :fitness_turnover_floor, :turnover_min,
     :turnover_max, :require_out_of_sample, :stability_min_positive_fraction,
     :cost_stress_multiplier, :cost_stress_sharpe_min, CAST(:extra AS jsonb),
     :config_hash, :author, :effective_from)
""")

SELECT = """
SELECT config_id, sharpe_min, fitness_min, fitness_turnover_floor, turnover_min, turnover_max,
       require_out_of_sample, stability_min_positive_fraction, cost_stress_multiplier,
       cost_stress_sharpe_min, extra, config_hash, author, effective_from, created_at
FROM alpha_gate_config
"""


def _to_stored(row: Any) -> StoredGateConfig:
    return StoredGateConfig(
        config_id=row.config_id,
        sharpe_min=row.sharpe_min,
        fitness_min=row.fitness_min,
        fitness_turnover_floor=row.fitness_turnover_floor,
        turnover_min=row.turnover_min,
        turnover_max=row.turnover_max,
        require_out_of_sample=row.require_out_of_sample,
        stability_min_positive_fraction=row.stability_min_positive_fraction,
        cost_stress_multiplier=row.cost_stress_multiplier,
        cost_stress_sharpe_min=row.cost_stress_sharpe_min,
        extra=row.extra,
        config_hash=row.config_hash,
        author=row.author,
        effective_from=row.effective_from,
        created_at=row.created_at,
    )


def get_gate_config(connection: Connection, config_id: str) -> StoredGateConfig:
    """One stored gate configuration."""
    row = connection.execute(
        text(f"{SELECT} WHERE config_id = :config_id"), {"config_id": config_id}
    ).one_or_none()
    if row is None:
        raise RegistryError(
            f"gate configuration {config_id} is not stored; "
            "run scripts/load_gates.py to put the settings file in the database"
        )
    return _to_stored(row)


def find_gate_config(connection: Connection, config_id: str) -> StoredGateConfig | None:
    """The stored configuration, or None when this version has never been loaded."""
    try:
        return get_gate_config(connection, config_id)
    except RegistryError:
        return None


def store_gate_config(
    connection: Connection,
    config: GatesConfig,
    *,
    author: str,
    effective_from: datetime | None = None,
) -> tuple[StoredGateConfig, bool]:
    """Store one gate version. Returns the row and whether it was newly written.

    Loading the same file twice changes nothing. Loading different values under the same
    version is refused, because results already judged by that version must keep their
    meaning.
    """
    fingerprint = config_hash(config)
    existing = find_gate_config(connection, config.version)

    if existing is not None:
        if existing.config_hash == fingerprint:
            return existing, False
        raise GateConfigMismatch(
            f"{config.version} is already stored with a different fingerprint "
            f"({existing.config_hash[:12]}... in the database, {fingerprint[:12]}... in the "
            "file). A changed gate is a new version: copy the file to gates_v2.yaml and "
            "record the reason in an ADR."
        )

    connection.execute(
        INSERT,
        {
            "config_id": config.version,
            "sharpe_min": Decimal(str(config.sharpe_min)),
            "fitness_min": Decimal(str(config.fitness_min)),
            "fitness_turnover_floor": Decimal(str(config.fitness_turnover_floor)),
            "turnover_min": Decimal(str(config.turnover_min)),
            "turnover_max": Decimal(str(config.turnover_max)),
            "require_out_of_sample": config.require_out_of_sample,
            "stability_min_positive_fraction": Decimal(str(config.stability_min_positive_fraction)),
            "cost_stress_multiplier": Decimal(str(config.cost_stress_multiplier)),
            "cost_stress_sharpe_min": Decimal(str(config.cost_stress_sharpe_min)),
            "extra": json.dumps({"stability_subperiod": config.stability_subperiod}),
            "config_hash": fingerprint,
            "author": author,
            "effective_from": effective_from or datetime.now(UTC),
        },
    )
    return get_gate_config(connection, config.version), True


def load_gate_config_file(
    connection: Connection,
    path: Path = DEFAULT_GATES_FILE,
    *,
    author: str,
    effective_from: datetime | None = None,
) -> tuple[StoredGateConfig, bool]:
    """Read a gates YAML file and store it."""
    return store_gate_config(
        connection, load_gates(path), author=author, effective_from=effective_from
    )


def check_matches_file(
    connection: Connection, config_id: str, path: Path = DEFAULT_GATES_FILE
) -> bool:
    """Whether the stored version still matches the settings file on disk."""
    return get_gate_config(connection, config_id).config_hash == config_hash(load_gates(path))


def list_gate_configs(connection: Connection) -> list[StoredGateConfig]:
    """Every stored gate version, newest first."""
    rows = connection.execute(text(f"{SELECT} ORDER BY effective_from DESC, config_id")).all()
    return [_to_stored(row) for row in rows]
