"""Versioned retrospective membership, session and source-unit controls.

This is a conditional research cohort, never a claim of certified PIT quotes.
No inferred ratio repairs: unresolved capital-action histories are quarantined.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

START = "2025-01-01"
END = "2026-06-30"
INCLUSIONS = {
    "ETERNAL": "2025-03-28",
    "JIOFIN": "2025-03-28",
    "INDIGO": "2025-09-30",
    "MAXHEALTH": "2025-09-30",
    "BSE": "2026-09-30",
}
EXCLUSIONS = {
    "BPCL": "2025-03-28",
    "BRITANNIA": "2025-03-28",
    "HEROMOTOCO": "2025-09-30",
    "INDUSINDBK": "2025-09-30",
}
TEMPORARY = {
    "ITCHOTELS": ("2025-01-06", "2025-02-10", "2025-01-29"),
    "TMCV": ("2025-10-14", "2025-11-17", "2025-11-12"),
    "KWIL": ("2025-12-05", "2026-02-24", "2026-02-16"),
}
# Explicit review quarantine, not a claim that every other history is certified.
UNIT_QUARANTINE = frozenset(
    {
        "BAJFINANCE",
        "BSE",
        "HDFCBANK",
        "KOTAKBANK",
        "NESTLEIND",
        "SHRIRAMFIN",
        "TRENT",
        "ITC",
        "TMPV",
        "HINDUNILVR",
        "ADANIENT",
    }
)


def membership(symbol: str, day: str) -> tuple[bool, bool]:
    """Membership includes non-tradable dummy constituents until listing."""
    if not START <= day <= END:
        raise ValueError("membership is bounded to the reviewed TRAIN/VALID window")
    if symbol in TEMPORARY:
        first, last, listed = TEMPORARY[symbol]
        return first <= day < last, first <= day < last and day >= listed
    included = day >= INCLUSIONS.get(symbol, START) and day < EXCLUSIONS.get(symbol, "9999")
    return included, included


def schedule(holidays: set[str]) -> dict[str, dict[str, Any]]:
    """Retrospective actual calendar; announcement timing/outage policy is separate."""
    result = {}
    day = date.fromisoformat(START)
    while str(day) <= END:
        key = str(day)
        if day.weekday() < 5 and key not in holidays:
            result[key] = dict(open_minute=555, slots=375, kind="normal")
        day += timedelta(days=1)
    for key in ("2025-02-01", "2026-02-01"):
        result[key] = dict(open_minute=555, slots=375, kind="budget")
    result["2025-10-21"] = dict(open_minute=825, slots=60, kind="muhurat")
    return dict(sorted(result.items()))


def parse_reviewed_candles(
    body: bytes, symbol: str, first: str, last: str, sessions: dict[str, dict[str, Any]]
) -> pd.DataFrame:
    payload = json.loads(body)
    if payload.get("status") != "success":
        raise ValueError("history refused or failed")
    candles = payload["data"]["candles"]
    if not isinstance(candles, list) or any(len(row) != 7 for row in candles):
        raise ValueError("unexpected candle schema")
    if not candles:
        return pd.DataFrame()
    frame = pd.DataFrame(
        candles, columns=["timestamp", "open", "high", "low", "close", "volume", "open_interest"]
    )
    stamps = pd.to_datetime(frame.timestamp, utc=True, errors="raise")
    local = stamps.dt.tz_convert("Asia/Kolkata")
    frame["session_date"] = local.dt.strftime("%Y-%m-%d")
    if not frame.session_date.between(first, last).all() or stamps.duplicated().any():
        raise ValueError("raw dates outside request or duplicate timestamp")
    values = frame[["open", "high", "low", "close", "volume"]].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values[:, :4] <= 0).any() or (values[:, 4] < 0).any():
        raise ValueError("invalid candle numbers")
    if (
        (frame.low > frame[["open", "close"]].min(axis=1))
        | (frame.high < frame[["open", "close"]].max(axis=1))
    ).any():
        raise ValueError("inconsistent OHLC")
    opening = frame.session_date.map({day: r["open_minute"] for day, r in sessions.items()})
    count = frame.session_date.map({day: r["slots"] for day, r in sessions.items()})
    minute = local.dt.hour * 60 + local.dt.minute
    mask = (minute >= opening) & (minute < opening + count) & (local.dt.second == 0)
    mask &= (local.dt.microsecond == 0) & (local.dt.nanosecond == 0)
    frame["symbol"] = symbol
    frame["timestamp"] = stamps
    frame["open_time"] = stamps.dt.as_unit("us").astype("int64")
    frame["available_at"] = stamps + pd.Timedelta(minutes=1)
    frame["full_bar"] = True
    frame["session_open_minute"] = opening
    frame["session_slots"] = count
    frame["source_close"] = frame.close
    frame["source_volume"] = frame.volume
    return (
        frame.loc[mask]
        .drop(columns="open_interest")
        .sort_values("open_time")
        .reset_index(drop=True)
    )


def verify_price_day(frame: pd.DataFrame, official: pd.Series[Any], symbol: str) -> str:
    """Conservative scale/identity screen, not minute-price or volume certification."""
    if symbol in UNIT_QUARANTINE:
        return "UNRESOLVED_CAPITAL_ACTION_UNITS"
    if frame.empty:
        return "NO_MINUTES"
    expected_aliases = {symbol} | ({"ZOMATO"} if symbol == "ETERNAL" else set())
    if str(official.TckrSymb) not in expected_aliases:
        return "IDENTITY_MISMATCH"
    a = np.array([frame.high.max(), frame.low.min()], dtype=float)
    b = np.array([official.HghPric, official.LwPric], dtype=float)
    if not np.isfinite(b).all() or (b <= 0).any():
        return "INVALID_DAILY_REFERENCE"
    # Fixed before new model/VALID results. Allows normal/auction endpoint scope
    # differences, but labels the result a screen rather than exact validation.
    return "PASS_SCALE_SCREEN" if np.max(np.abs(a / b - 1)) <= 0.002 else "DAILY_SCALE_MISMATCH"


def verified_file(root: Path, relative: str, digest: str) -> Path:
    from helios.data.equities import sha256

    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or sha256(path) != digest:
        raise ValueError("rebuild source path/hash mismatch")
    return path
