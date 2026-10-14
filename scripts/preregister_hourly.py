import argparse
import json
from pathlib import Path

from helios.alpha.hourly_hypotheses import preregister_hourly
from helios.common.db import get_engine
from helios.common.lineage import git_is_dirty
from helios.data.snapshots import compute_snapshot_id, load_manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Preregister eight fixed hourly hypotheses; no evaluation"
    )
    parser.add_argument("--snapshot-id", required=True)
    args = parser.parse_args()
    if git_is_dirty():
        raise ValueError("preregistration requires committed hypothesis source")
    snapshot = load_manifest(args.snapshot_id)
    if (
        snapshot.interval != "1h"
        or compute_snapshot_id(snapshot.files) != args.snapshot_id
        or "BTCUSDT" not in snapshot.symbols
    ):
        raise ValueError("hourly BTC snapshot required")
    with get_engine().begin() as connection:
        experiments = preregister_hourly(connection, args.snapshot_id)
    out = Path("reports_out/hourly_hypotheses_protocol.json")
    with out.open("x") as handle:
        json.dump([e.model_dump(mode="json") for e in experiments], handle, indent=2)
    print(json.dumps({e.params["definition"]["alpha_id"]: e.experiment_id for e in experiments}))


if __name__ == "__main__":
    main()
