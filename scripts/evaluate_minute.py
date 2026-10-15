"""Register and execute the fixed preregistered minute VALID round once."""

import json
from pathlib import Path

from helios.alpha.minute_round import minute_requests
from helios.common.db import get_engine
from helios.common.lineage import git_is_dirty
from helios.registry.experiments import ExperimentStatus, set_status
from helios.sim.evaluate import evaluate


def main() -> int:
    if git_is_dirty():
        raise ValueError("minute measurements require clean committed source")
    destination = Path("reports_out/minute_round1/outcomes.json")
    if destination.exists():
        raise ValueError("minute round manifest already retained; no automatic rerun")
    engine = get_engine()
    with engine.begin() as c:
        requests = minute_requests(c, register=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    outcomes = []
    for request in requests:
        with engine.begin() as c:
            set_status(c, request.experiment_id, ExperimentStatus.RUNNING)
        try:
            result = evaluate(
                request.alpha_id,
                request.split,
                request.experiment_id,
                config=request.config,
                output_dir=destination.parent / "evaluations",
            )
        except Exception as exc:
            with engine.begin() as c:
                set_status(c, request.experiment_id, ExperimentStatus.ABANDONED)
            outcomes.append(
                dict(
                    alpha_id=request.alpha_id,
                    experiment_id=request.experiment_id,
                    status="FAILED",
                    error=type(exc).__name__,
                )
            )
            destination.write_text(json.dumps(outcomes, indent=2) + "\n")
            print(json.dumps(outcomes[-1]), flush=True)
            raise
        with engine.begin() as c:
            set_status(c, request.experiment_id, ExperimentStatus.FINISHED)
        assert result.evaluation_json is not None
        outcomes.append(
            dict(
                alpha_id=result.alpha_id,
                experiment_id=result.experiment_id,
                run_id=result.run_id,
                status=result.status.value,
                artifact_sha256=result.evaluation_json["artifact_sha256"],
            )
        )
        destination.write_text(json.dumps(outcomes, indent=2) + "\n")
        print(json.dumps(outcomes[-1]), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
