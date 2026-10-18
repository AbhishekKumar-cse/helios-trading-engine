"""Verified source adapter. Feature availability never depends on future labels."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from helios.common.config import config_hash
from helios.data.equities import EquityPilotConfig, constituents, sha256
from helios.equities.calendar import snapshot_sessions
from helios.equities.config import EquityResearchPolicy
from helios.equities.features import minute_samples
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
    if policy.interval == "1m":
        return load_minute_inputs(snapshot, symbol, policy)
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


def load_minute_inputs(snapshot: Path, symbol: str, policy: EquityResearchPolicy) -> EquityInputs:
    manifest: dict[str, Any] = json.loads((snapshot / "manifest.json").read_text())
    if policy.version == "nse_minute_research_v2":
        return load_repaired_inputs(snapshot, symbol, policy)
    if manifest["version"] != "nse_public_minutes_v1":
        raise ValueError("minute input must be an immutable public minute snapshot")
    hashes = {"manifest": sha256(snapshot / "manifest.json")}
    for name, key in (
        ("constituents.csv", "universe_sha256"),
        ("protocol.json", "protocol_sha256"),
        ("requests.jsonl", "requests_sha256"),
    ):
        if sha256(snapshot / name) != manifest[key]:
            raise ValueError("minute snapshot source checksum mismatch")
        hashes[name] = manifest[key]
    protocol = json.loads((snapshot / "protocol.json").read_text())
    if protocol["end"] < policy.valid_end.isoformat():
        raise ValueError("minute snapshot does not reach the frozen VALID boundary")
    record = next((row for row in manifest["files"] if row["symbol"] == symbol), None)
    if record is None:
        raise ValueError("no minute history for frozen constituent")
    path = snapshot / record["path"]
    if not path.resolve().is_relative_to(snapshot.resolve()) or sha256(path) != record["sha256"]:
        raise ValueError("minute input fingerprint mismatch")
    hashes[record["path"]] = record["sha256"]
    with (snapshot / "requests.jsonl").open() as journal:
        for line in journal:
            request = json.loads(line)
            if request["symbol"] == symbol:
                if "sha256" not in request:
                    raise ValueError("minute source contains an incomplete month")
                raw = snapshot / request["path"]
                if (
                    not raw.resolve().is_relative_to(snapshot.resolve())
                    or sha256(raw) != request["sha256"]
                ):
                    raise ValueError("raw minute source fingerprint mismatch")
                hashes[request["path"]] = request["sha256"]
    bars = pd.read_parquet(path, filters=[("session_date", "<=", policy.valid_end.isoformat())])
    if bars.empty or set(bars.symbol) != {symbol}:
        raise ValueError("minute input identity mismatch")
    samples = minute_samples(bars, include_unlabelled=True)
    values = samples[list(features_for("60m"))].copy()
    available = pd.DataFrame(
        {name: samples.feature_available for name in values}, index=values.index
    )
    features = FeatureFrame(symbol, samples.open_time, values.where(available), available)
    dates, calendar_hashes = snapshot_sessions(snapshot, policy.valid_start, policy.valid_end)
    hashes.update(calendar_hashes)
    return EquityInputs(symbol, bars, features, dates, hashes)


def load_repaired_inputs(snapshot: Path, symbol: str, policy: EquityResearchPolicy) -> EquityInputs:
    from helios.equities.rebuild import membership, verified_file

    manifest: dict[str, Any] = json.loads((snapshot / "manifest.json").read_text())
    if (
        manifest["version"] != "nse_public_minutes_v2"
        or not manifest["complete"]
        or manifest["test_access"]
        or manifest["g7_eligible"]
    ):
        raise ValueError("v2 requires a completed conditional, TEST-sealed snapshot")
    hashes = {"manifest": sha256(snapshot / "manifest.json")}
    for name, key in (
        ("protocol.json", "protocol_sha256"),
        ("sessions.json", "sessions_sha256"),
        ("universe.json", "universe_sha256"),
        ("session_checks.json", "checks_sha256"),
    ):
        verified_file(snapshot, name, manifest[key])
        hashes[name] = manifest[key]
    protocol = json.loads((snapshot / "protocol.json").read_text())
    if protocol["start"] != "2025-01-01" or protocol["end"] != policy.valid_end.isoformat():
        raise ValueError("repaired snapshot split mismatch")
    records = [r for r in manifest["files"] if r["symbol"] == symbol]
    if len(records) != 1 or records[0]["eligible_rows"] <= 0:
        raise ValueError("no screened observations for this historical member")
    record = records[0]
    path = verified_file(snapshot, record["path"], record["sha256"])
    hashes[record["path"]] = record["sha256"]
    bars = pd.read_parquet(path)
    if (
        set(bars.symbol) != {symbol}
        or bars.open_time.duplicated().any()
        or not bars.session_date.between("2025-01-01", policy.valid_end.isoformat()).all()
    ):
        raise ValueError("repaired source dates/identity mismatch")
    if not all(membership(symbol, day)[1] for day in bars.session_date.unique()):
        raise ValueError("repaired source contains out-of-membership observations")
    bars = bars.loc[bars.research_eligible].reset_index(drop=True)
    if set(bars.screen_status) != {"PASS_SCALE_SCREEN"}:
        raise ValueError("quarantined prices cannot enter research")
    sessions = json.loads((snapshot / "sessions.json").read_text())
    for day, part in bars.groupby("session_date"):
        setting = sessions[day]
        if (
            len(part) != setting["slots"]
            or set(part.session_slots) != {setting["slots"]}
            or set(part.session_open_minute) != {setting["open_minute"]}
        ):
            raise ValueError("repaired session schedule/coverage mismatch")
    samples = minute_samples(bars, include_unlabelled=True)
    values = samples[list(features_for("60m"))].copy()
    available = pd.DataFrame(
        {name: samples.feature_available for name in values}, index=values.index
    )
    features = FeatureFrame(symbol, samples.open_time, values.where(available), available)
    dates = tuple(record["expected_valid_sessions"])
    expected = tuple(
        d
        for d in sessions
        if policy.valid_start.isoformat() <= d <= policy.valid_end.isoformat()
        and membership(symbol, d)[1]
    )
    if dates != expected:
        raise ValueError("expected-session denominator differs from historical membership")
    return EquityInputs(symbol, bars, features, dates, hashes)
