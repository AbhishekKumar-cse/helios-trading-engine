"""Fixed minute round, frozen before measurements; no TEST or automatic retests."""

from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import Connection, text

from helios.alpha.definition import (
    AlphaDefinition,
    load_alpha_definition,
    register_alpha_definition,
)
from helios.alpha.hourly_hypotheses import HOURLY_HYPOTHESES
from helios.common.config import config_hash
from helios.common.lineage import git_commit
from helios.common.project_config import HorizonFamily, load_minute_stage
from helios.registry.api import get_alpha
from helios.registry.experiments import (
    ExperimentStatus,
    register_experiment,
    require_open_experiment,
)
from helios.registry.results import Split
from helios.sim.evaluate import EvaluationConfig
from helios.sim.many import EvaluationRequest

AUTHOR = "helios_minute_round1"
PRIOR = (
    "All hourly quantitative and ML results are known; minute feature preprocessing is complete. "
    "No minute measurement or selection has been made."
)


def minute_definitions() -> tuple[AlphaDefinition, ...]:
    root = Path(__file__).resolve().parents[3] / "configs/alphas/baselines"
    definitions = []
    for i, name in enumerate(("b0_momentum", "b1_reversal", "b2_taker_flow")):
        d = load_alpha_definition(root / f"{name}.yaml")
        definitions.append(
            d.model_copy(
                update=dict(
                    alpha_id=f"minute_b{i}",
                    name=d.name.replace("hourly", "minute"),
                    horizon_family=HorizonFamily.MINUTE,
                    code_commit=git_commit(),
                )
            )
        )
    for idea in HOURLY_HYPOTHESES:
        d = idea.definition()
        definitions.append(
            d.model_copy(
                update=dict(
                    alpha_id=d.alpha_id.replace("hourly_", "minute_"),
                    name="Minute " + d.name,
                    horizon_family=HorizonFamily.MINUTE,
                    code_commit=git_commit(),
                )
            )
        )
    return tuple(definitions)


def minute_protocol(definition: AlphaDefinition) -> dict[str, object]:
    return dict(
        definition=definition.model_dump(mode="json", exclude={"code_commit"}),
        evaluation=EvaluationConfig(interval="1m").model_dump(mode="json"),
        stage=load_minute_stage().model_dump(mode="json"),
        test_access=False,
        tune=False,
        retain_all=True,
        prior_exposure=PRIOR,
    )


def preregister_minute(connection: Connection, snapshot_id: str) -> tuple[int, ...]:
    if connection.execute(
        text("SELECT EXISTS(SELECT 1 FROM experiments WHERE author=:a)"), {"a": AUTHOR}
    ).scalar_one():
        raise ValueError("minute round already preregistered; retain the original attempts")
    return tuple(
        register_experiment(
            connection,
            hypothesis="Fixed minute " + d.name + " may retain direction after accepted costs.",
            params={"protocol": minute_protocol(d)},
            author=AUTHOR,
            snapshot_id=snapshot_id,
            code_commit=git_commit(),
            config_hash=config_hash(d),
        ).experiment_id
        for d in minute_definitions()
    )


def minute_requests(
    connection: Connection, *, register: bool = False
) -> tuple[EvaluationRequest, ...]:
    requests: list[EvaluationRequest] = []
    for d in minute_definitions():
        rows: Sequence[int] = (
            connection.execute(
                text("""SELECT experiment_id FROM experiments WHERE author=:a
            AND params->'protocol'->'definition'->>'alpha_id'=:id"""),
                {"a": AUTHOR, "id": d.alpha_id},
            )
            .scalars()
            .all()
        )
        if len(rows) != 1:
            raise ValueError("each minute idea requires exactly one preregistered experiment")
        e = require_open_experiment(connection, rows[0])
        if e.status is not ExperimentStatus.PLANNED or e.params.get("protocol") != minute_protocol(
            d
        ):
            raise ValueError(
                "fixed minute definition/evaluation/stage differs from preregistration"
            )
        if connection.execute(
            text("SELECT count(*) FROM alpha_results WHERE experiment_id=:id"),
            {"id": e.experiment_id},
        ).scalar_one():
            raise ValueError("minute attempt already retained; no silent retry")
        if register:
            register_alpha_definition(connection, d)
        else:
            stored = get_alpha(connection, d.alpha_id, 1)
            if stored.model_dump(
                exclude={"code_commit", "created_at"}
            ) != d.to_registry().model_dump(exclude={"code_commit", "created_at"}):
                raise ValueError("registered minute definition differs from preregistration")
        requests.append(
            EvaluationRequest(
                d.alpha_id, Split.VALID, e.experiment_id, EvaluationConfig(interval="1m")
            )
        )
    return tuple(requests)
