"""Verified source adapter. Feature availability never depends on future labels."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from helios.common.config import config_hash
from helios.data.equities import EquityPilotConfig, constituents, sha256
from helios.equities.config import EquityResearchPolicy
from helios.features.runner import FeatureFrame
from helios.ml.equity_pilot import features_and_labels, features_for


@dataclass(frozen=True)
class EquityInputs:
    symbol: str
    bars: pd.DataFrame
    features: FeatureFrame
    expected_sessions: tuple[str, ...]
    hashes: dict[str, str]


def load_equity_inputs(snapshot: Path, symbol: str, policy: EquityResearchPolicy) -> EquityInputs:
    manifest: dict[str, Any] = json.loads((snapshot / "manifest.json").read_text())
    protocol = EquityPilotConfig.model_validate_json((snapshot / "protocol.json").read_text())
    if config_hash(protocol) != manifest["config_hash"]:
        raise ValueError("equity snapshot protocol mismatch")
    if (policy.train_end, policy.valid_start, policy.valid_end) != (
        protocol.hourly_train_end,
        protocol.hourly_valid_start,
        protocol.hourly_valid_end,
    ):
        raise ValueError("research dates must match the frozen equity snapshot split")
    roster = snapshot / "constituents.csv"
    if sha256(roster) != manifest["universe_sha256"]:
        raise ValueError("constituent snapshot mismatch")
    if symbol not in {row["Symbol"] for row in constituents(roster.read_bytes())}:
        raise ValueError("symbol is outside the frozen official universe")
    frames, hashes = {}, {"manifest": sha256(snapshot / "manifest.json")}
    for interval in ("60m", "1d"):
        records = [
            r for r in manifest["files"] if r["symbol"] == symbol and r["interval"] == interval
        ]
        if len(records) != 1:
            raise ValueError("expected one source file per equity interval")
        record = records[0]
        for field, digest in (("path", "sha256"), ("raw_path", "raw_sha256")):
            path = snapshot / record[field]
            if (
                not path.resolve().is_relative_to(snapshot.resolve())
                or sha256(path) != record[digest]
            ):
                raise ValueError("equity source checksum mismatch")
            hashes[record[field]] = record[digest]
        frames[interval] = pd.read_parquet(
            snapshot / record["path"],
            filters=[("session_date", "<=", policy.valid_end.isoformat())],
        )
    bars = frames["60m"].copy().reset_index(drop=True)
    bars["open_time"] = bars.timestamp.dt.as_unit("us").astype("int64")
    samples = features_and_labels(bars, "60m", include_unlabelled=True)
    values = samples[list(features_for("60m"))].copy()
    available = pd.DataFrame(
        {name: samples.feature_available for name in values.columns}, index=values.index
    )
    features = FeatureFrame(
        symbol,
        samples.timestamp.dt.as_unit("us").astype("int64"),
        values.where(available),
        available,
    )
    daily = frames["1d"]
    eligible = daily.session_date.between(
        policy.valid_start.isoformat(), policy.valid_end.isoformat()
    )
    dates = tuple(sorted(set(daily.loc[eligible, "session_date"])))
    dates = tuple(day for day in dates if pd.Timestamp(day).weekday() < 5)
    return EquityInputs(symbol, bars, features, dates, hashes)
