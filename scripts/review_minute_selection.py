"""Verify minute TEST eligibility; optionally journal the gate-mandated empty shortlist."""

import argparse
import json
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text

from helios.alpha.minute_selection import reject_ineligible_minute, review_minute
from helios.common.db import get_engine
from helios.common.lineage import git_commit, git_is_dirty


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--finalize-skip", action="store_true")
    args = parser.parse_args()
    if git_is_dirty():
        raise ValueError("reported minute selection requires clean source")
    with get_engine().begin() as connection:
        connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
        review = review_minute(connection)
        decisions = reject_ineligible_minute(connection, review) if args.finalize_skip else []
        after = review_minute(connection)
        if review != after:
            raise ValueError("research or TEST access changed during selection")
    payload = dict(
        source_commit=git_commit(),
        dirty=False,
        review=review,
        decisions=decisions,
        observations_loaded=False,
        test_executed=False,
    )
    directory = Path("reports_out/minute_selection") / str(uuid4())
    directory.mkdir(parents=True, exist_ok=False)
    path = directory / "review.json"
    with path.open("x") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(path)


if __name__ == "__main__":
    main()
