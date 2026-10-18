"""Attach an immutable official normal-session calendar to an equity snapshot."""

import argparse
import shutil
from datetime import UTC, date, datetime
from pathlib import Path

from helios.data.equities import sha256, write_json
from helios.equities.calendar import normal_sessions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw", type=Path)
    parser.add_argument("snapshot", type=Path)
    args = parser.parse_args()
    dates = normal_sessions(args.raw, date(2026, 1, 1), date(2026, 12, 31))
    target = args.snapshot / "nse_holidays_raw.json"
    if target.exists() or (args.snapshot / "calendar.json").exists():
        raise ValueError("retained calendar cannot be overwritten")
    shutil.copyfile(args.raw, target)
    write_json(
        args.snapshot / "calendar.json",
        dict(
            version="nse_official_normal_calendar_2026_v1",
            path=target.name,
            sha256=sha256(target),
            source="https://www.nseindia.com/api/holiday-master?type=trading",
            year=2026,
            checked_at=datetime.now(UTC).isoformat(),
            normal_sessions=len(dates),
            special_sessions="excluded; historical point-in-time schedule not claimed",
        ),
    )
    print(f"Frozen official calendar: {len(dates)} normal weekday sessions")


if __name__ == "__main__":
    main()
