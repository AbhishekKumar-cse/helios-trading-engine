"""Explicit normal NSE session clock; continuous UTC remains the default."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
MINUTE_US = 60_000_000


def nse_bar_complete(open_time: int, close_time: int, interval: str) -> bool:
    local = datetime.fromtimestamp(open_time / 1_000_000, UTC).astimezone(IST)
    minute = local.hour * 60 + local.minute
    if local.weekday() >= 5 or local.second or local.microsecond or not 555 <= minute < 930:
        return False
    if interval == "1h":
        return (minute - 555) % 60 == 0 and close_time - open_time == min(
            60, 930 - minute
        ) * MINUTE_US
    return interval == "1m" and close_time - open_time == MINUTE_US


def nse_reviewed_bar_complete(open_time: int, close_time: int, interval: str) -> bool:
    """Bounded v2 minute grid; actual holiday membership is checked by inputs."""
    local = datetime.fromtimestamp(open_time / 1_000_000, UTC).astimezone(IST)
    day = local.date().isoformat()
    if not "2025-01-01" <= day <= "2026-06-30" or interval != "1m":
        return False
    if local.second or local.microsecond or close_time - open_time != MINUTE_US:
        return False
    minute = local.hour * 60 + local.minute
    if day == "2025-10-21":
        return 825 <= minute < 885
    if local.weekday() >= 5 and day not in ("2025-02-01", "2026-02-01"):
        return False
    return 555 <= minute < 930
