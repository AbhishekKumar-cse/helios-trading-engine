"""Bind each fixed candidate to its exact experiment; VALID only (129)."""

from pathlib import Path

from sqlalchemy import Connection, text

from helios.alpha.hourly_round import HOURLY_DIR, load_hourly_definitions, registered_experiment
from helios.registry.api import get_alpha
from helios.registry.experiments import require_open_experiment
from helios.registry.results import Split
from helios.sim.evaluate import EvaluationConfig
from helios.sim.many import EvaluationRequest


def hourly_requests(
    connection: Connection, directory: Path = HOURLY_DIR
) -> tuple[EvaluationRequest, ...]:
    requests = []
    for definition in load_hourly_definitions(directory):
        experiment_id = registered_experiment(connection, definition)
        experiment = require_open_experiment(connection, experiment_id)
        if experiment.params.get("evaluation") != dict(
            symbol="BTCUSDT", split="valid", warmup_rows=168, seed=0
        ):
            raise ValueError("evaluation differs from the preregistered VALID protocol")
        stored = get_alpha(connection, definition.alpha_id, definition.version)
        if stored.model_dump(
            exclude={"code_commit", "created_at"}
        ) != definition.to_registry().model_dump(exclude={"code_commit", "created_at"}):
            raise ValueError("registered definition differs from the fixed YAML")
        existing: int = connection.execute(
            text("SELECT count(*) FROM alpha_results WHERE experiment_id=:id"),
            {"id": experiment_id},
        ).scalar_one()
        if existing:
            raise ValueError("attempt already retained; do not silently rerun this experiment")
        requests.append(
            EvaluationRequest(
                definition.alpha_id,
                Split.VALID,
                experiment_id,
                EvaluationConfig(symbol="BTCUSDT", warmup_rows=168, seed=0),
            )
        )
    return tuple(requests)
