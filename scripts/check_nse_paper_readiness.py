"""Read-only operational preflight; a readiness report is never a PAPER trial."""

import argparse
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text

from helios.common.db import get_engine
from helios.common.lineage import git_commit, git_is_dirty
from helios.data.equities import sha256, write_json
from helios.equities.service import session_is_open


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calendar", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("preflight evidence must not be overwritten")
    now = datetime.now(UTC)
    opened, dirty = session_is_open(now, args.calendar), git_is_dirty()
    with get_engine().connect() as connection:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        instrument = (
            connection.execute(
                text(
                    "SELECT symbol,venue,quote_asset,tick_size,lot_size FROM instruments "
                    "WHERE symbol='RELIANCE'"
                )
            )
            .mappings()
            .one_or_none()
        )
        test_accesses = connection.execute(
            text("SELECT count(*) FROM test_set_access")
        ).scalar_one()
    failures = []
    if not opened:
        failures.append("NORMAL_NSE_SESSION_CLOSED")
    if dirty:
        failures.append("REPORTED_PAPER_REQUIRES_CLEAN_SOURCE")
    if (
        instrument is None
        or instrument["venue"] != "nse_cash"
        or instrument["quote_asset"] != "INR"
    ):
        failures.append("NSE_INSTRUMENT_METADATA_MISSING")
    write_json(
        args.output,
        dict(
            version="nse_paper_preflight_v1",
            checked_at=now.isoformat(),
            code_commit=git_commit(),
            dirty=dirty,
            calendar_sha256=sha256(args.calendar),
            normal_session_open=opened,
            integration_run_ready=not failures,
            blockers=failures,
            instrument=None if instrument is None else {k: str(v) for k, v in instrument.items()},
            test_accesses=test_accesses,
            observations_collected=0,
            fills_created=0,
            market_hours_validated=False,
            trial_24h_completed=False,
            trial_7d_completed=False,
            note=(
                "Read-only preflight. No feed observation, "
                "elapsed trading trial or candidate promotion."
            ),
        ),
    )


if __name__ == "__main__":
    main()
