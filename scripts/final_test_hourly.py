"""Save the final TEST decision; execute only an eligible frozen VALID shortlist."""

import argparse
import json
from pathlib import Path
from uuid import uuid4

from helios.alpha.final_test import prepare_final_test
from helios.common.db import get_engine
from helios.common.lineage import git_commit, git_is_dirty
from helios.common.project_config import load_fees, load_gates, load_splits
from helios.data.binance import sha256_file
from helios.registry.experiments import (
    ExperimentStatus,
    register_experiment,
    set_status,
)
from helios.registry.results import Split
from helios.sim.evaluate import EvaluationConfig, evaluate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if git_is_dirty():
        raise ValueError("final TEST decision requires clean source")
    engine = get_engine()
    with engine.connect() as connection:
        plan = prepare_final_test(connection)
    plan["source_commit"] = git_commit()
    directory = Path("reports_out/hourly_final_test") / str(uuid4())
    directory.mkdir(parents=True, exist_ok=False)
    path = directory / "plan.json"
    path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
    # This branch never loads observations or consumes a counter when the list is empty.
    outcomes = []
    if args.execute:
        for selected in plan["selected"]:
            with engine.begin() as connection:
                experiment = register_experiment(
                    connection,
                    author="helios_hourly_confirmation",
                    hypothesis="Frozen VALID-passing hourly candidate survives final TEST.",
                    params=dict(
                        selection=selected,
                        plan_sha256=sha256_file(path),
                        splits=load_splits().model_dump(mode="json"),
                        fees=load_fees().model_dump(mode="json"),
                        gates=load_gates().model_dump(mode="json"),
                    ),
                    code_commit=git_commit(),
                    snapshot_id=selected["snapshot_id"],
                    notes="No TEST-driven changes; reservation precedes loader.",
                )
                set_status(connection, experiment.experiment_id, ExperimentStatus.RUNNING)
            try:
                result = evaluate(
                    selected["alpha_id"],
                    Split.TEST,
                    experiment.experiment_id,
                    config=EvaluationConfig(version=selected["version"]),
                    actor="helios_hourly",
                    purpose="One final confirmation of frozen VALID-passing candidate",
                )
            except Exception:
                with engine.begin() as connection:
                    set_status(connection, experiment.experiment_id, ExperimentStatus.ABANDONED)
                raise
            with engine.begin() as connection:
                set_status(connection, experiment.experiment_id, ExperimentStatus.FINISHED)
            outcomes.append(
                dict(alpha_id=result.alpha_id, run_id=result.run_id, status=result.status.value)
            )
    with (directory / "outcomes.json").open("x") as handle:
        json.dump(outcomes, handle, indent=2)
        handle.write("\n")
    print(path)


if __name__ == "__main__":
    main()
