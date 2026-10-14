"""Load and atomically register exact preregistered hourly definitions (128)."""

from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import Connection, text

from helios.alpha.definition import (
    AlphaDefinition,
    load_alpha_definition,
    register_alpha_definition,
)
from helios.alpha.hourly_hypotheses import HOURLY_HYPOTHESES
from helios.registry.experiments import require_open_experiment

HOURLY_DIR = Path(__file__).resolve().parents[3] / "configs/alphas/hourly"


def load_hourly_definitions(directory: Path = HOURLY_DIR) -> tuple[AlphaDefinition, ...]:
    files = {p.name for p in directory.glob("*.yaml")}
    expected = {h.alpha_id + ".yaml" for h in HOURLY_HYPOTHESES}
    if files != expected:
        raise ValueError("hourly directory must contain exactly the eight preregistered files")
    definitions = []
    for idea in HOURLY_HYPOTHESES:
        definition = load_alpha_definition(directory / (idea.alpha_id + ".yaml"))
        if definition.model_dump(
            mode="json", exclude={"code_commit"}
        ) != idea.definition().model_dump(mode="json", exclude={"code_commit"}):
            raise ValueError("YAML differs from the fixed hypothesis")
        definitions.append(definition)
    return tuple(definitions)


def registered_experiment(connection: Connection, definition: AlphaDefinition) -> int:
    rows: Sequence[int] = (
        connection.execute(
            text(
                "SELECT experiment_id FROM experiments "
                "WHERE author='helios_hourly' AND params->'definition'->>'alpha_id'=:alpha "
                "AND params->'definition'->>'version'=:version"
            ),
            {"alpha": definition.alpha_id, "version": str(definition.version)},
        )
        .scalars()
        .all()
    )
    if len(rows) != 1:
        raise ValueError("candidate requires exactly one preregistered experiment")
    experiment = require_open_experiment(connection, int(rows[0]))
    if experiment.params.get("definition") != definition.model_dump(
        mode="json", exclude={"code_commit"}
    ):
        raise ValueError("definition does not match preregistration")
    return experiment.experiment_id


def register_hourly(connection: Connection, directory: Path = HOURLY_DIR) -> tuple[str, ...]:
    definitions = load_hourly_definitions(directory)
    for definition in definitions:
        registered_experiment(connection, definition)
    for definition in definitions:
        register_alpha_definition(connection, definition)
    return tuple(d.alpha_id for d in definitions)
