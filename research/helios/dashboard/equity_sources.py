"""Read-only public minute history discovery with content and boundary checks."""

import json
from pathlib import Path
from typing import Any

import pandas as pd

from helios.data.equities import sha256


def public_minute_snapshot(root: Path) -> tuple[Path, dict[str, Any]] | None:
    paths = sorted((root / "data/equities/nifty50_minutes").glob("*/manifest.json"), reverse=True)
    if not paths:
        return None
    path = paths[0]
    manifest: dict[str, Any] = json.loads(path.read_text())
    if (
        manifest["version"] != "nse_public_minutes_v1"
        or sha256(path.parent / "constituents.csv") != manifest["universe_sha256"]
    ):
        raise ValueError("public minute snapshot identity mismatch")
    return path.parent, manifest


def read_public_minutes(snapshot: Path, manifest: dict[str, Any], symbol: str) -> pd.DataFrame:
    records = [row for row in manifest["files"] if row["symbol"] == symbol]
    if len(records) != 1:
        raise ValueError("public minute company unavailable")
    record = records[0]
    source = snapshot / record["path"]
    if (
        not source.resolve().is_relative_to(snapshot.resolve())
        or sha256(source) != record["sha256"]
    ):
        raise ValueError("public minute price fingerprint mismatch")
    # The published first minute protocol reserves July onward; this history
    # stops at June. Never use wall-clock 'today' as a research display boundary.
    return pd.read_parquet(source, filters=[("session_date", "<=", "2026-06-30")])
