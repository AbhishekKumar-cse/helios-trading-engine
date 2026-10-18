"""Credential-free, rate-limited historical candle collector; never an order API."""

from __future__ import annotations

import argparse
import calendar
import json
import math
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from helios.common.lineage import git_commit
from helios.data.equities import constituents, sha256, write_json

BASE = "https://api.upstox.com/v3/historical-candle/"
DOCUMENTATION = "https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/"


def month_ranges(start: date, end: date) -> list[tuple[date, date]]:
    if start > end:
        raise ValueError("historical range must be chronological")
    result = []
    while start <= end:
        last = min(end, start.replace(day=calendar.monthrange(start.year, start.month)[1]))
        result.append((start, last))
        start = last + timedelta(days=1)
    return result


def history_url(isin: str, start: date, end: date) -> str:
    if len(isin) != 12 or not isin.isalnum() or not isin.startswith("IN"):
        raise ValueError("a frozen Indian ISIN is required")
    return BASE + urllib.parse.quote("NSE_EQ|" + isin, safe="") + f"/minutes/1/{end}/{start}"


def fetch_public(url: str) -> bytes:
    if not url.startswith((BASE, "https://www.nseindia.com/api/holiday-master?")):
        raise ValueError("only allowlisted public historical/calendar endpoints are supported")
    for attempt in range(4):
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "HELIOS academic historical research",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body: bytes = response.read()
                return body
        except urllib.error.HTTPError as error:
            # An authentication refusal is terminal; never attempt a workaround.
            if error.code not in (429, 500, 502, 503, 504) or attempt == 3:
                raise
            time.sleep(min(30, 2 ** (attempt + 1)))
        except (urllib.error.URLError, TimeoutError):
            if attempt == 3:
                raise
            time.sleep(2 ** (attempt + 1))
    raise AssertionError("unreachable")


def parse_candles(
    body: bytes, symbol: str, start: date, end: date
) -> tuple[pd.DataFrame, dict[str, int]]:
    payload = json.loads(body)
    if payload.get("status") != "success" or not isinstance(
        payload.get("data", {}).get("candles"), list
    ):
        raise ValueError("public history did not return a candle list")
    rows: list[dict[str, Any]] = []
    excluded: Counter[str] = Counter()
    seen: set[int] = set()
    for candle in payload["data"]["candles"]:
        if not isinstance(candle, list) or len(candle) != 7:
            raise ValueError("unexpected historical candle schema")
        stamp = pd.Timestamp(candle[0])
        if stamp.tzinfo is None:
            raise ValueError("historical timestamps must declare their timezone")
        local = stamp.tz_convert("Asia/Kolkata")
        clock = int(stamp.value // 1000)
        if clock in seen:
            raise ValueError("duplicate historical timestamp")
        seen.add(clock)
        if not start <= local.date() <= end:
            raise ValueError("historical API returned an observation outside the requested range")
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in candle[1:6]
        ):
            excluded["nonfinite_or_nonnumeric"] += 1
            continue
        opening, high, low, close, volume = map(float, candle[1:6])
        if (
            min(opening, high, low, close) <= 0
            or volume < 0
            or low > min(opening, close)
            or high < max(opening, close)
        ):
            excluded["invalid_ohlcv"] += 1
            continue
        minute = local.hour * 60 + local.minute
        if local.weekday() >= 5 or not 555 <= minute < 930 or local.second or local.microsecond:
            excluded["nonstandard_session"] += 1
            continue
        rows.append(
            dict(
                symbol=symbol,
                timestamp=stamp.tz_convert("UTC"),
                open_time=clock,
                session_date=local.date().isoformat(),
                available_at=stamp.tz_convert("UTC") + pd.Timedelta(minutes=1),
                open=opening,
                high=high,
                low=low,
                close=close,
                adjusted_close=close,
                volume=volume,
                full_bar=True,
            )
        )
    return pd.DataFrame(rows), dict(excluded)


def collect_minutes(roster_path: Path, output: Path, start: date, end: date) -> Path:
    roster = constituents(roster_path.read_bytes())
    if end >= datetime.now(UTC).date():
        raise ValueError("historical collector only requests past completed dates")
    output.mkdir(parents=True, exist_ok=False)
    (output / "raw").mkdir()
    (output / "bars").mkdir()
    shutil.copyfile(roster_path, output / "constituents.csv")
    write_json(
        output / "protocol.json",
        dict(
            version="nse_public_minutes_v1",
            source="upstox_public_history",
            start=start,
            end=end,
            interval="1m",
            documentation=DOCUMENTATION,
            credential_free=True,
            source_commit=git_commit(),
            purpose="personal academic research; no redistribution claim",
            source_sha256=sha256(Path(__file__)),
        ),
    )
    shutil.copyfile(Path(__file__), output / "collector_source.py")
    records: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    with (output / "requests.jsonl").open("x") as journal:
        for number, member in enumerate(roster, 1):
            symbol, isin = member["Symbol"], member["ISIN Code"]
            chunks = []
            for first, last in month_ranges(start, end):
                url = history_url(isin, first, last)
                path = output / "raw" / f"{symbol}_{first}_{last}.json"
                before = time.monotonic()
                try:
                    body = fetch_public(url)
                    path.write_bytes(body)
                    frame, excluded = parse_candles(body, symbol, first, last)
                    row = dict(
                        symbol=symbol,
                        isin=isin,
                        start=str(first),
                        end=str(last),
                        url=url,
                        path=str(path.relative_to(output)),
                        sha256=sha256(path),
                        rows=len(frame),
                        excluded=excluded,
                    )
                    if not frame.empty:
                        chunks.append(frame)
                except (ValueError, urllib.error.URLError, TimeoutError) as error:
                    row = dict(
                        symbol=symbol,
                        isin=isin,
                        start=str(first),
                        end=str(last),
                        url=url,
                        error_type=type(error).__name__,
                    )
                    failures.append(
                        dict(
                            symbol=symbol,
                            start=str(first),
                            end=str(last),
                            error_type=type(error).__name__,
                        )
                    )
                    if isinstance(error, urllib.error.HTTPError) and error.code in (401, 403):
                        journal.write(json.dumps(row) + "\n")
                        journal.flush()
                        raise RuntimeError(
                            "public history requires access; collector stopped"
                        ) from None
                journal.write(json.dumps(row) + "\n")
                journal.flush()
                time.sleep(max(0, 0.6 - (time.monotonic() - before)))
            if chunks:
                frame = pd.concat(chunks).sort_values("open_time").reset_index(drop=True)
                if frame.open_time.duplicated().any():
                    raise ValueError("overlapping historical requests produced duplicate bars")
                path = output / "bars" / f"{symbol}.parquet"
                frame.to_parquet(path, index=False)
                records.append(
                    dict(
                        symbol=symbol,
                        isin=isin,
                        path=str(path.relative_to(output)),
                        sha256=sha256(path),
                        rows=len(frame),
                        first_session=frame.session_date.min(),
                        last_session=frame.session_date.max(),
                    )
                )
            else:
                failures.append(dict(symbol=symbol, error_type="no_observed_history"))
            print(
                f"{number}/50 {symbol}: {sum(len(part) for part in chunks)} real minute bars",
                flush=True,
            )
    write_json(
        output / "manifest.json",
        dict(
            version="nse_public_minutes_v1",
            source="upstox_public_history",
            interval="1m",
            universe_sha256=sha256(output / "constituents.csv"),
            protocol_sha256=sha256(output / "protocol.json"),
            requests_sha256=sha256(output / "requests.jsonl"),
            files=records,
            failures=failures,
            created_at=datetime.now(UTC).isoformat(),
            current_universe=True,
            corporate_actions_verified=False,
        ),
    )
    print(f"Retained: {output / 'manifest.json'}", flush=True)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roster", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2025, 1, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 6, 30))
    args = parser.parse_args()
    collect_minutes(args.roster, args.output, args.start, args.end)


if __name__ == "__main__":
    main()
