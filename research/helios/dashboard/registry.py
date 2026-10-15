import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine, text

from helios.common.db import get_engine
from helios.registry.api import list_alphas
from helios.registry.results import get_result, list_results
from helios.registry.selection import get_selection
from helios.sim.report import DEFAULT_REPORT_ROOT, generate_report


def registry_rows(connection: Connection) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    definitions, attempts = [], []
    for definition in list_alphas(connection, latest_only=False):
        results = list_results(
            connection, alpha_id=definition.alpha_id, version=definition.version, limit=10000
        )
        count: int = connection.execute(
            text("SELECT count(*) FROM alpha_results WHERE alpha_id=:id AND version=:v"),
            {"id": definition.alpha_id, "v": definition.version},
        ).scalar_one()
        if count != len(results):
            raise ValueError("registry view must not silently truncate retained attempts")
        latest = results[0] if results else None
        selection = get_selection(
            connection,
            definition.alpha_id,
            definition.version,
            "minute_round1" if definition.horizon_family.value == "H-MINUTE" else "hourly_round1",
        )
        definitions.append(
            dict(
                Alpha=definition.alpha_id,
                Version=definition.version,
                Name=definition.name,
                Family=definition.horizon_family.value,
                Provenance=definition.provenance.value.upper(),
                Measurement=latest.status.value if latest else "DRAFT",
                Selection=selection.status if selection else "UNDECIDED",
                Attempts=len(results),
                Synthetic=bool(definition.spec.get("is_synthetic", False)),
                Report=f"?run={latest.run_id}" if latest else None,
            )
        )
        for result in results:
            attempts.append(
                dict(
                    Alpha=result.alpha_id,
                    Version=result.version,
                    Split=result.split.value.upper(),
                    Status=result.status.value,
                    Sharpe=None if result.sharpe is None else float(result.sharpe),
                    Fitness=None if result.fitness is None else float(result.fitness),
                    Run=result.run_id,
                    Report=f"?run={result.run_id}",
                )
            )
    return definitions, attempts


def read_registry(
    engine: Engine | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    with (get_engine() if engine is None else engine).connect() as connection:
        connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        return registry_rows(connection)


def report_html(run_id: str, *, engine: Engine | None = None) -> str:
    try:
        if str(uuid.UUID(run_id)) != run_id:
            raise ValueError("noncanonical report identifier")
    except (ValueError, TypeError) as exc:
        raise ValueError("report requires a canonical retained run UUID") from exc
    with (get_engine() if engine is None else engine).connect() as connection:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        result = get_result(connection, run_id)
    # Derivative HTML is isolated by retained run; source evidence remains immutable.
    path = generate_report(result, output_root=DEFAULT_REPORT_ROOT / "dashboard" / run_id)
    return Path(path).read_text(encoding="utf-8")
