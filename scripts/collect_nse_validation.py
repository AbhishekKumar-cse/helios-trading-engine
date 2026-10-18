"""Retain public reference evidence for the existing 2025–June2026 minute snapshot.

No credentials, price TEST downloads, result writes, source repairs or promotion.
HTTP refusals are retained, never bypassed. All outputs are exclusive-created.
"""

import argparse
import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from helios.common.lineage import git_commit
from helios.data.equities import constituents, sha256, write_json

REFERENCES = {
    "nse_levies": "https://www.nseindia.com/static/invest/first-time-investor-sebi-turnover-fees-stt-other-levies",
    "exchange_cost_20241001": "https://nsearchives.nseindia.com/content/circulars/FA64232.pdf",
    "exchange_cost_20260301": "https://nsearchives.nseindia.com/content/circulars/FA73061.pdf",
    "broker_charges_current": "https://zerodha.com/charges/",
    "broker_ipft_current": "https://support.zerodha.com/category/account-opening/resident-individual/ri-charges/articles/ipft-charges",
    "budget_session_2026": "https://nsearchives.nseindia.com/content/circulars/CMTR72349.pdf",
    "index_20250328": "https://www.niftyindices.com/Press_Release/ind_prs21022025.pdf",
    "index_20250930": "https://www.niftyindices.com/Press_Release/ind_prs22082025.pdf",
    "index_20260330": "https://www.niftyindices.com/Press_Release/ind_prs23022026.pdf",
    "index_20260930": "https://www.niftyindices.com/Press_Release/ind_prs10082026.pdf",
    "itc_demerg_exclusion": "https://www.niftyindices.com/Press_Release/ind_prs06022025_1.pdf",
    "nse_daily_reports": "https://www.nseindia.com/all-reports",
}


def retain(url: str, path: Path) -> dict[str, Any]:
    """One normal public request; no auth/session workaround or denied-request retry."""
    if urllib.parse.urlsplit(url).hostname not in {
        "www.nseindia.com",
        "nsearchives.nseindia.com",
        "www.niftyindices.com",
        "zerodha.com",
        "support.zerodha.com",
    }:
        raise ValueError("reference host is not allowlisted")
    before = datetime.now(UTC).isoformat()
    record: dict[str, Any] = dict(url=url, retrieved_at=before, path=path.name)
    request = urllib.request.Request(url, headers={"User-Agent": "HELIOS academic validation"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
            record.update(status=response.status, content_type=response.headers.get("Content-Type"))
    except urllib.error.HTTPError as error:
        body = error.read()
        record.update(status=error.code, error=type(error).__name__)
    except (urllib.error.URLError, TimeoutError) as error:
        body = b""
        record.update(status=None, error=type(error).__name__)
    with path.open("xb") as handle:
        handle.write(body)
    record.update(sha256=sha256(path), bytes=len(body))
    time.sleep(0.25)
    return record


def collect(snapshot: Path, output: Path) -> None:
    manifest = json.loads((snapshot / "manifest.json").read_text())
    protocol = json.loads((snapshot / "protocol.json").read_text())
    if (
        manifest["version"] != "nse_public_minutes_v1"
        or protocol["start"] != "2025-01-01"
        or protocol["end"] != "2026-06-30"
        or sha256(snapshot / "constituents.csv") != manifest["universe_sha256"]
        or sha256(snapshot / "protocol.json") != manifest["protocol_sha256"]
    ):
        raise ValueError("this reference audit is bounded to the frozen TRAIN/VALID snapshot")
    roster = constituents((snapshot / "constituents.csv").read_bytes())
    output.mkdir(parents=True, exist_ok=False)
    (output / "raw").mkdir()
    write_json(
        output / "protocol.json",
        dict(
            version="nse_public_reference_audit_v1",
            source_commit=git_commit(),
            snapshot=str(snapshot.resolve()),
            snapshot_manifest_sha256=sha256(snapshot / "manifest.json"),
            start=protocol["start"],
            end=protocol["end"],
            test_prices_requested=False,
            monthly_sampling="First Tuesday, fixed before any price comparison; failures retained.",
            action_sampling="Each non-dividend ex-date and prior weekday; no imputation.",
            source_sha256=sha256(Path(__file__)),
            references=REFERENCES,
        ),
    )
    records = []
    with (output / "requests.jsonl").open("x") as journal:

        def request(key: str, url: str) -> dict[str, Any]:
            record = retain(url, output / "raw" / (key + ".raw"))
            record["key"] = key
            record["path"] = "raw/" + record["path"]
            records.append(record)
            journal.write(json.dumps(record) + "\n")
            journal.flush()
            print(key, record["status"], record["bytes"], flush=True)
            return record

        for key, url in REFERENCES.items():
            request(key, url)
        days = {date(2025, 2, 1), date(2026, 2, 1)}
        for year in (2025, 2026):
            for month in range(1, 13 if year == 2025 else 7):
                first = date(year, month, 1)
                days.add(first + timedelta(days=(1 - first.weekday()) % 7))
        for member in roster:
            symbol = member["Symbol"]
            query = urllib.parse.urlencode(
                dict(index="equities", symbol=symbol, from_date="01-01-2025", to_date="30-06-2026")
            )
            record = request(
                "actions_" + symbol,
                "https://www.nseindia.com/api/corporates-corporateActions?" + query,
            )
            if record["status"] != 200:
                continue
            actions = json.loads((output / record["path"]).read_bytes())
            if not isinstance(actions, list):
                raise ValueError("corporate actions must be a list; retain failure for review")
            for action in actions:
                if "dividend" in str(action.get("subject", "")).lower():
                    continue
                day = datetime.strptime(action["exDate"], "%d-%b-%Y").date()
                if not date(2025, 1, 1) <= day <= date(2026, 6, 30):
                    raise ValueError("corporate endpoint returned a date outside the audit")
                days.add(day)
                previous = day - timedelta(days=1)
                while previous.weekday() >= 5:
                    previous -= timedelta(days=1)
                if previous >= date(2025, 1, 1):
                    days.add(previous)
        for day in sorted(days):
            record = request(
                "bhav_" + day.isoformat(),
                "https://nsearchives.nseindia.com/content/cm/"
                f"BhavCopy_NSE_CM_0_0_0_{day:%Y%m%d}_F_0000.csv.zip",
            )
            if record["status"] == 200:
                with ZipFile(io.BytesIO((output / record["path"]).read_bytes())) as archive:
                    if len(archive.namelist()) != 1:
                        raise ValueError("expected exactly one official bhavcopy CSV")
    write_json(
        output / "manifest.json",
        dict(
            version="nse_public_reference_audit_v1",
            snapshot_manifest_sha256=sha256(snapshot / "manifest.json"),
            protocol_sha256=sha256(output / "protocol.json"),
            requests_sha256=sha256(output / "requests.jsonl"),
            sources=records,
            complete=True,
        ),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    collect(args.snapshot, args.output)
