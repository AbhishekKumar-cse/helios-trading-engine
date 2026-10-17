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
