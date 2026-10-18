"""Strict, read-only checks for retained public NSE reference evidence."""

from __future__ import annotations

import io
import json
import re
from datetime import date, datetime
from math import isfinite
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import pandas as pd

from helios.data.equities import sha256


def verified_references(root: Path) -> dict[str, dict[str, Any]]:
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest["version"] != "nse_public_reference_audit_v1" or not manifest["complete"]:
        raise ValueError("reference collection has not completed")
    for name in ("protocol", "requests"):
        suffix = ".json" if name == "protocol" else ".jsonl"
        if sha256(root / (name + suffix)) != manifest[name + "_sha256"]:
            raise ValueError("reference collection protocol/journal changed")
    journal = [json.loads(line) for line in (root / "requests.jsonl").read_text().splitlines()]
    if journal != manifest["sources"]:
        raise ValueError("reference manifest differs from retained request journal")
    records = {}
    for row in manifest["sources"]:
        path = (root / row["path"]).resolve()
        if (
            not path.is_relative_to(root.resolve())
            or sha256(path) != row["sha256"]
            or row["key"] in records
        ):
            raise ValueError("reference identity/path/hash mismatch")
        records[row["key"]] = row
    return records


def corporate_events(body: bytes, symbol: str, start: date, end: date) -> list[dict[str, Any]]:
    payload = json.loads(body)
    if not isinstance(payload, list):
        raise ValueError("corporate actions must be a list, not an error response")
    events = []
    for row in payload:
        if row["symbol"] != symbol or row["series"] != "EQ":
            raise ValueError("corporate-action symbol or series mismatch")
        day = datetime.strptime(row["exDate"], "%d-%b-%Y").date()
        if not start <= day <= end or not re.fullmatch(r"IN[A-Z0-9]{10}", row["isin"]):
            raise ValueError("corporate action outside audit dates or invalid ISIN")
        subject = row["subject"].strip()
        if not subject:
            raise ValueError("corporate action lacks a purpose")
        events.append(
            dict(
                symbol=symbol,
                ex_date=day.isoformat(),
                subject=subject,
                reported_isin=row["isin"],
                broadcast=row.get("caBroadcastDate"),
                point_in_time_availability_verified=False,
                kind="dividend" if "dividend" in subject.lower() else "capital_or_other",
            )
        )
    return events


def bhavcopy(body: bytes, expected_day: date) -> pd.DataFrame:
    with ZipFile(io.BytesIO(body)) as archive:
        names = archive.namelist()
        if len(names) != 1 or not names[0].endswith(".csv"):
            raise ValueError("expected one official bhavcopy CSV")
        frame = pd.read_csv(archive.open(names[0]), keep_default_na=False)
    required = {
        "TradDt",
        "ISIN",
        "TckrSymb",
        "SctySrs",
        "OpnPric",
        "HghPric",
        "LwPric",
        "ClsPric",
        "LastPric",
        "TtlTradgVol",
    }
    if not required.issubset(frame) or set(frame.TradDt) != {expected_day.isoformat()}:
        raise ValueError("bhavcopy schema or actual trade date mismatch")
    frame = frame.loc[frame.SctySrs == "EQ"].copy()
    if frame.ISIN.duplicated().any():
        raise ValueError("ambiguous official EQ instrument identity")
    return frame


def known_preinclusion_rows(days: pd.Series[Any], *, included_on: date) -> pd.Series[bool]:
    """Retrospective known violation mask; not proof of all other membership dates."""
    normalized = pd.to_datetime(days, format="%Y-%m-%d", errors="raise")
    if normalized.isna().any():
        raise ValueError("membership audit requires an actual date for every row")
    return pd.Series(normalized.dt.date < included_on, index=days.index, dtype=bool)


def price_scale_check(minute: pd.DataFrame, official: pd.Series[Any]) -> dict[str, Any]:
    """Daily audit of sampled price basis, not a claim of equal trading universes.

    Official close is a closing-price benchmark, not necessarily last minute close.
    Volume/preopen/postclose definitions may differ. Never repair on a ratio alone.
    """
    if minute.empty:
        return {"status": "NO_RETAINED_MINUTES"}
    high, low = float(official.HghPric), float(official.LwPric)
    if not all(isfinite(value) and value > 0 for value in (high, low)) or low > high:
        raise ValueError("official prices must be positive")
    observed_high, observed_low = float(minute.high.max()), float(minute.low.min())
    if not all(isfinite(value) and value > 0 for value in (observed_high, observed_low)):
        raise ValueError("minute comparison requires finite positive prices")
    ratios = (observed_high / high, observed_low / low)
    # A 5% same-direction shift in both extremes flags incompatible price scales.
    scale = min(ratios) > 1.05 or max(ratios) < 0.95
    return dict(
        status="PRICE_SCALE_REVIEW" if scale else "NO_LARGE_SCALE_SHIFT_DETECTED",
        minute_rows=len(minute),
        minute_high=observed_high,
        minute_low=observed_low,
        official_high=high,
        official_low=low,
        high_ratio=ratios[0],
        low_ratio=ratios[1],
        minute_last=float(minute.close.iloc[-1]),
        official_close=float(official.ClsPric),
        official_last=float(official.LastPric),
        minute_volume=float(minute.volume.sum()),
        official_volume=float(official.TtlTradgVol),
    )
