"""Explicit normal-session dates from a retained official NSE CM holiday response."""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from helios.data.equities import sha256


def normal_sessions(raw: Path, start: date, end: date) -> tuple[str, ...]:
    payload = json.loads(raw.read_bytes())
    entries = payload.get("CM")
    if not isinstance(entries, list) or not entries:
        raise ValueError("official NSE capital-market calendar is missing")
    holidays = {datetime.strptime(row["tradingDate"], "%d-%b-%Y").date() for row in entries}
    years = {day.year for day in holidays}
    if start.year not in years or end.year not in years or start > end:
        raise ValueError("requested dates are outside the retained official calendar")
    result = []
    while start <= end:
        if start.weekday() < 5 and start not in holidays:
            result.append(start.isoformat())
        start += timedelta(days=1)
    return tuple(result)


def snapshot_sessions(
    snapshot: Path, start: date, end: date
) -> tuple[tuple[str, ...], dict[str, str]]:
    descriptor = json.loads((snapshot / "calendar.json").read_text())
    raw = snapshot / descriptor["path"]
    if not raw.resolve().is_relative_to(snapshot.resolve()) or sha256(raw) != descriptor["sha256"]:
        raise ValueError("official calendar fingerprint mismatch")
    return normal_sessions(raw, start, end), {
        "calendar.json": sha256(snapshot / "calendar.json"),
        descriptor["path"]: descriptor["sha256"],
    }
