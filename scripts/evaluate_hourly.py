import json
from dataclasses import asdict
from pathlib import Path

from helios.alpha.hourly_evaluation import hourly_requests
from helios.common.db import get_engine
from helios.common.lineage import git_is_dirty
from helios.registry.experiments import ExperimentStatus, set_status
from helios.sim.many import evaluate_many


def main() -> int:
    if git_is_dirty():
        raise ValueError("reported hourly evaluation requires clean source")
    path = Path("reports_out/hourly_hypotheses_outcomes.json")
    if path.exists():
        raise ValueError("round outcome manifest already exists; retain it")
    with get_engine().begin() as connection:
        requests = hourly_requests(connection)
        for request in requests:
            set_status(connection, request.experiment_id, ExperimentStatus.RUNNING)
    outcomes = evaluate_many(requests, workers=2)
    with path.open("x") as handle:
        json.dump([asdict(o) for o in outcomes], handle, indent=2)
    for outcome in outcomes:
        print(json.dumps(asdict(outcome)), flush=True)
    return int(any(o.error is not None for o in outcomes))


if __name__ == "__main__":
    raise SystemExit(main())
