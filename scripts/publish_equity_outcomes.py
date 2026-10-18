"""Publish already-stored results after coordinator failure; no evaluation or DB writes."""

import argparse
import json
from pathlib import Path

from sqlalchemy import text

from helios.common.db import get_engine
from helios.common.lineage import PROJECT_ROOT
from helios.data.equities import sha256
from helios.registry.results import get_result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("round_id")
    args = parser.parse_args()
    root = PROJECT_ROOT / "reports_out/equity_research" / args.round_id
    attempts = json.loads((root / "preregistration.json").read_text())["attempts"]
    protocol = json.loads((root / "protocol.json").read_text())
    path = root / "outcomes.jsonl"
    original = path.read_bytes()
    retained = [json.loads(line) for line in original.splitlines()]
    known = {row["experiment_id"] for row in retained}
    rows = []
    with get_engine().connect() as connection:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        for attempt in attempts:
            if attempt["experiment_id"] in known:
                continue
            ids = (
                connection.execute(
                    text("""SELECT r.run_id FROM alpha_results r
                JOIN experiments e USING(experiment_id)
                WHERE experiment_id=:id AND e.status='finished'"""),
                    dict(id=attempt["experiment_id"]),
                )
                .scalars()
                .all()
            )
            if not ids:
                continue
            if len(ids) != 1:
                raise ValueError("one preregistered attempt has multiple results")
            result = get_result(connection, ids[0])
            assert result.alpha_id == attempt["alpha_id"] and result.split.value == "valid"
            assert result.code_commit == protocol["source_commit"]
            evidence = result.evaluation_json
            assert sha256(Path(evidence["artifact"])) == evidence["artifact_sha256"]
            rows.append(
                attempt
                | dict(
                    run_id=result.run_id,
                    status=result.status.value,
                    sharpe=None if result.sharpe is None else float(result.sharpe),
                    fitness=None if result.fitness is None else float(result.fitness),
                    gates=result.gate_results,
                    artifact=evidence["artifact"],
                    artifact_sha256=evidence["artifact_sha256"],
                )
            )
    if path.read_bytes() != original:
        raise ValueError("outcomes changed concurrently; retry publication")
    with path.open("a") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    print(f"Published {len(rows)} existing results; no simulation or registry mutation")


if __name__ == "__main__":
    main()
