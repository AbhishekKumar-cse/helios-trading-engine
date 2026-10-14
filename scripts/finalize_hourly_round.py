"""Record round-one selection without rewriting any measured result."""

import argparse
import json
from pathlib import Path
from uuid import uuid4

from helios.alpha.search_effort import CANDIDATES
from helios.common.db import get_engine
from helios.common.lineage import git_is_dirty
from helios.registry.api import get_alpha
from helios.registry.results import Split, list_results
from helios.registry.selection import record_selection


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-plan", required=True, type=Path)
    args = parser.parse_args()
    if git_is_dirty():
        raise ValueError("reported selection decisions require clean source")
    plan = json.loads(args.test_plan.read_text())
    outcomes = json.loads((args.test_plan.parent / "outcomes.json").read_text())
    expected = {s["alpha_id"] for s in plan["selected"]}
    if expected != {o["alpha_id"] for o in outcomes}:
        raise ValueError(
            "every shortlisted candidate needs its retained TEST outcome before selection"
        )
    confirmation = {o["alpha_id"]: o["run_id"] for o in outcomes}
    decisions = []
    with get_engine().begin() as connection:
        for alpha_id in CANDIDATES:
            definition = get_alpha(connection, alpha_id)
            rows = list_results(
                connection,
                alpha_id=alpha_id,
                version=definition.version,
                split=Split.VALID,
                limit=10000,
            )
            if not rows:
                raise ValueError("candidate has no retained VALID attempt")
            valid = max(
                rows, key=lambda r: (r.created_at.timestamp() if r.created_at else 0, r.run_id)
            )
            selected = next((s for s in plan["selected"] if s["alpha_id"] == alpha_id), None)
            if selected is not None and selected["valid_run_id"] != valid.run_id:
                raise ValueError("VALID evidence changed after TEST shortlist was frozen")
            decisions.append(
                record_selection(
                    connection,
                    round_id="hourly_round1",
                    valid_run_id=valid.run_id,
                    test_run_id=confirmation.get(alpha_id),
                    actor="helios_hourly",
                )
            )
    directory = Path("reports_out/hourly_selection") / str(uuid4())
    directory.mkdir(parents=True, exist_ok=False)
    path = directory / "decisions.json"
    with path.open("x") as handle:
        json.dump([d.model_dump(mode="json") for d in decisions], handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(path)


if __name__ == "__main__":
    main()
