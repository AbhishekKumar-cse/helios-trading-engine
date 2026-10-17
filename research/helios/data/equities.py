"""Immutable Nifty constituent snapshots and Yahoo-distributed NSE equity bars.

Separate from Binance's continuous calendar, symbols and adjustment assumptions.
No authentication, order endpoints, imputation, or invented historical membership.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import pandas as pd
from pydantic import Field, StrictInt, model_validator

from helios.common.config import HeliosConfig, config_hash, load_config

IST = ZoneInfo("Asia/Kolkata")
ROSTER_URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv"
Interval = Literal["1d", "60m", "1m"]
INTERVALS: tuple[Interval, ...] = ("1d", "60m", "1m")


class EquityPilotConfig(HeliosConfig):
    version: Literal["nifty50_equity_pilot_v1"]
    daily_start: date
    hourly_start: date
    minute_start: date
    end_exclusive: date
    daily_train_end: date
    daily_valid_start: date
    daily_valid_end: date
    daily_test_start: date
    hourly_train_end: date
    hourly_valid_start: date
    hourly_valid_end: date
    hourly_test_start: date
    seed: StrictInt = Field(ge=0)
    n_estimators: StrictInt = Field(ge=2)
    num_leaves: StrictInt = Field(ge=2)
    min_child_samples: StrictInt = Field(ge=1)
    learning_rate: float = Field(gt=0, le=1, allow_inf_nan=False)
    stopping_rounds: StrictInt = Field(ge=1)

    @model_validator(mode="after")
    def ordered_windows(self) -> EquityPilotConfig:
        for frequency in ("daily", "hourly"):
            start = getattr(self, f"{frequency}_start")
            train_end = getattr(self, f"{frequency}_train_end")
            valid_start = getattr(self, f"{frequency}_valid_start")
            valid_end = getattr(self, f"{frequency}_valid_end")
            test_start = getattr(self, f"{frequency}_test_start")
            if not start < train_end < valid_start < valid_end < test_start < self.end_exclusive:
                raise ValueError("equity split dates must be strictly chronological")
            if min((valid_start - train_end).days, (test_start - valid_end).days) < 8:
                raise ValueError("equity pilot needs at least seven embargo calendar days")
        return self


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: object) -> None:
    """Exclusive creation: an existing snapshot/run is never overwritten."""
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False, default=str)
        handle.write("\n")


def constituents(body: bytes) -> list[dict[str, str]]:
    rows = list(csv.DictReader(io.StringIO(body.decode("utf-8-sig"))))
    if len(rows) != 50:
        raise ValueError(f"expected exactly 50 official constituents, received {len(rows)}")
    symbols: set[str] = set()
    isins: set[str] = set()
    for row in rows:
        symbol, isin = row["Symbol"], row["ISIN Code"]
        if row["Series"] != "EQ" or not re.fullmatch(r"[A-Z0-9&-]+", symbol):
            raise ValueError("unexpected constituent symbol/series")
        if not re.fullmatch(r"IN[A-Z0-9]{10}", isin) or symbol in symbols or isin in isins:
            raise ValueError("invalid or duplicate constituent identity")
        symbols.add(symbol)
        isins.add(isin)
    return sorted(rows, key=lambda row: row["Symbol"])


def download(url: str) -> bytes:
    """Small bounded retry for transient service errors; no access-control bypass."""
    for attempt in range(3):
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "HELIOS-academic-research/0.1"}
            )
            with urllib.request.urlopen(request, timeout=35) as response:
                body: bytes = response.read()
                return body
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(2 ** (attempt + 1))
    raise AssertionError("unreachable")


def chart_url(symbol: str, interval: Interval, start: date, end: date) -> str:
    query = urllib.parse.urlencode(
        dict(
            period1=int(datetime.combine(start, datetime.min.time(), IST).timestamp()),
            period2=int(datetime.combine(end, datetime.min.time(), IST).timestamp()),
            interval=interval,
            events="div,splits",
            includePrePost="false",
        )
    )
    ticker = urllib.parse.quote(symbol + ".NS", safe="")
    return f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?{query}"


def parse_chart(
    body: bytes, symbol: str, interval: Interval, start: date, end: date
) -> tuple[pd.DataFrame, dict[str, object]]:
    payload: Any = json.loads(body)
    if payload["chart"].get("error"):
        raise ValueError(str(payload["chart"]["error"]))
    result = payload["chart"]["result"][0]
    meta = result["meta"]
    if meta["symbol"] != symbol + ".NS" or meta.get("currency") != "INR":
        raise ValueError("vendor ticker/currency does not match requested NSE equity")
    if meta.get("exchangeTimezoneName") != "Asia/Kolkata":
        raise ValueError("unexpected exchange timezone")
    if meta.get("exchangeName") not in ("NSI", "NSE"):
        raise ValueError("unexpected listing exchange")
    quotes = result["indicators"]["quote"][0]
    stamps = result.get("timestamp", [])
    adjusted = result["indicators"].get("adjclose", [{}])[0].get("adjclose")
    rows: list[dict[str, object]] = []
    rejected: Counter[str] = Counter()
    seen: set[int] = set()
    for index, stamp in enumerate(stamps):
        when = datetime.fromtimestamp(stamp, IST)
        if stamp in seen:
            raise ValueError("duplicate vendor bar timestamp")
        seen.add(stamp)
        if not start <= when.date() < end:
            rejected["outside_requested_dates"] += 1
            continue
        values = [quotes[key][index] for key in ("open", "high", "low", "close", "volume")]
        adj = adjusted[index] if adjusted is not None else values[3]
        if interval == "1d" and adjusted is None:
            raise ValueError("daily adjusted close is required")
        if any(value is None or not math.isfinite(float(value)) for value in [*values, adj]):
            rejected["missing_or_nonfinite"] += 1
            continue
        opening, high, low, close, volume = (float(value) for value in values)
        if min(opening, high, low, close, float(adj)) <= 0 or volume < 0:
            rejected["invalid_price_or_volume"] += 1
            continue
        tolerance = high * 1e-6
        if low > min(opening, close) + tolerance or high + tolerance < max(opening, close):
            rejected["inconsistent_ohlc"] += 1
            continue
        minute = when.hour * 60 + when.minute
        # Normal session only for intraday. Special sessions stay in raw, explicitly excluded.
        if interval != "1d" and not 555 <= minute < 930:
            rejected["outside_normal_session"] += 1
            continue
        duration = 60 if interval == "60m" else 1
        full_bar = interval == "1d" or (minute + duration <= 930 and (minute - 555) % duration == 0)
        available = (
            datetime.combine(when.date() + timedelta(days=1), datetime.min.time(), IST)
            if interval == "1d"
            else when + timedelta(minutes=min(duration, 930 - minute))
        )
        rows.append(
            dict(
                symbol=symbol,
                timestamp=when.astimezone(UTC),
                session_date=when.date().isoformat(),
                available_at=available.astimezone(UTC),
                open=opening,
                high=high,
                low=low,
                close=close,
                volume=volume,
                adjusted_close=float(adj),
                full_bar=full_bar,
            )
        )
    if not rows:
        raise ValueError("no usable vendor bars")
    frame = pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)
    if not frame["timestamp"].is_monotonic_increasing:
        raise ValueError("bars not chronologically ordered")
    return frame, dict(
        raw_bars=len(stamps),
        retained_bars=len(frame),
        rejected_rows=dict(rejected),
        partial_bars=int((~frame["full_bar"]).sum()),
        zero_volume_bars=int((frame["volume"] == 0).sum()),
        first_session=frame["session_date"].min(),
        last_session=frame["session_date"].max(),
        corporate_actions=result.get("events", {}),
        exchange=meta.get("exchangeName"),
        currency="INR",
    )


def collect(config: EquityPilotConfig, root: Path) -> Path:
    if config.end_exclusive > datetime.now(IST).date():
        raise ValueError("end_exclusive must exclude the current incomplete session")
    snapshot = root / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8])
    snapshot.mkdir(parents=True, exist_ok=False)
    (snapshot / "raw").mkdir()
    (snapshot / "bars").mkdir()
    roster = download(ROSTER_URL)
    members = constituents(roster)
    (snapshot / "constituents.csv").write_bytes(roster)
    write_json(snapshot / "protocol.json", config.model_dump(mode="json"))
    manifest: dict[str, Any] = dict(
        version="nifty50_vendor_snapshot_v1",
        created_at=datetime.now(UTC).isoformat(),
        universe_source=ROSTER_URL,
        universe_sha256=sha256(snapshot / "constituents.csv"),
        universe_kind="current constituents at download; NOT historical index membership",
        provider=(
            "Yahoo Finance public chart API; NSE-listed equities, NOT official NSE price files"
        ),
        config_hash=config_hash(config),
        protocol_sha256=sha256(snapshot / "protocol.json"),
        adjustment=(
            "vendor quote OHLC (split adjustments may already apply); daily adjclose retained"
        ),
        source_file_sha256=sha256(Path(__file__)),
        members=members,
        files=[],
        failures=[],
    )
    starts: dict[Interval, date] = {
        "1d": config.daily_start,
        "60m": config.hourly_start,
        "1m": config.minute_start,
    }
    for member in members:
        symbol = member["Symbol"]
        for interval in INTERVALS:
            url = chart_url(symbol, interval, starts[interval], config.end_exclusive)
            raw = snapshot / "raw" / f"{symbol}_{interval}.json"
            try:
                body = download(url)
                raw.write_bytes(body)
                frame, quality = parse_chart(
                    body, symbol, interval, starts[interval], config.end_exclusive
                )
                destination = snapshot / "bars" / f"{symbol}_{interval}.parquet"
                frame.to_parquet(destination, index=False)
                manifest["files"].append(
                    dict(
                        symbol=symbol,
                        interval=interval,
                        url=url,
                        fetched_at=datetime.now(UTC).isoformat(),
                        raw_path=str(raw.relative_to(snapshot)),
                        raw_sha256=sha256(raw),
                        path=str(destination.relative_to(snapshot)),
                        sha256=sha256(destination),
                        **quality,
                    )
                )
                print(f"{symbol:14} {interval:3} {len(frame):6} bars", flush=True)
            except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
                manifest["failures"].append(
                    dict(
                        symbol=symbol,
                        interval=interval,
                        url=url,
                        error=f"{type(exc).__name__}: {exc}",
                        raw_sha256=sha256(raw) if raw.exists() else None,
                    )
                )
                print(f"FAILED {symbol} {interval}: {exc}", flush=True)
            time.sleep(0.25)
    write_json(snapshot / "manifest.json", manifest)
    print(f"Snapshot: {snapshot}; failures: {len(manifest['failures'])}", flush=True)
    return snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/equities/nifty50_pilot.yaml"))
    parser.add_argument("--root", type=Path, default=Path("data/equities/nifty50"))
    args = parser.parse_args()
    collect(load_config(args.config, EquityPilotConfig), args.root)


if __name__ == "__main__":
    main()
