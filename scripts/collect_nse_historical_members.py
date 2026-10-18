"""Retrieve only missing historical members/listed dummy windows, no TEST prices."""

import argparse
import json
import shutil
import time
import urllib.error
import urllib.parse
from datetime import date
from pathlib import Path

from collect_nse_validation import retain

from helios.data.equities import sha256, write_json
from helios.equities.public_data import fetch_public, history_url, month_ranges


def collect(identities: Path, output: Path) -> None:
    members = json.loads(identities.read_text())
    if any(not "2025-01-01" <= r["start"] <= r["end"] <= "2026-06-30" for r in members):
        raise ValueError("historical retrieval must remain in TRAIN/VALID")
    output.mkdir(parents=True, exist_ok=False)
    (output / "raw").mkdir()
    shutil.copyfile(__file__, output / "collector_source.py")
    shutil.copyfile(identities, output / "identities.json")
    write_json(
        output / "protocol.json",
        dict(
            version="nse_historical_members_v1",
            identities_sha256=sha256(identities),
            collector_sha256=sha256(Path(__file__)),
            test_prices_requested=False,
        ),
    )
    rows = []
    with (output / "requests.jsonl").open("x") as journal:
        for member in members:
            query = urllib.parse.urlencode(
                dict(
                    index="equities",
                    symbol=member["symbol"],
                    from_date="01-01-2025",
                    to_date="30-06-2026",
                )
            )
            action = retain(
                "https://www.nseindia.com/api/corporates-corporateActions?" + query,
                output / "raw" / ("actions_" + member["symbol"] + ".raw"),
            )
            action.update(kind="actions", symbol=member["symbol"], path="raw/" + action["path"])
            rows.append(action)
            journal.write(json.dumps(action) + "\n")
            journal.flush()
            for first, last in month_ranges(
                date.fromisoformat(member["start"]), date.fromisoformat(member["end"])
            ):
                path = output / "raw" / f"{member['symbol']}_{first}_{last}.json"
                url = history_url(member["isin"], first, last)
                record = dict(
                    kind="minutes",
                    symbol=member["symbol"],
                    isin=member["isin"],
                    start=str(first),
                    end=str(last),
                    url=url,
                    path=str(path.relative_to(output)),
                )
                try:
                    body = fetch_public(url)
                    with path.open("xb") as handle:
                        handle.write(body)
                    payload = json.loads(body)
                    record.update(
                        status=200,
                        sha256=sha256(path),
                        candles=len(payload.get("data", {}).get("candles", [])),
                    )
                except (urllib.error.URLError, TimeoutError, ValueError) as error:
                    record.update(status=getattr(error, "code", None), error=type(error).__name__)
                rows.append(record)
                journal.write(json.dumps(record) + "\n")
                journal.flush()
                print(member["symbol"], first, record.get("candles"), record["status"], flush=True)
                if record["status"] in (401, 403):
                    raise RuntimeError("public access refused; no authentication workaround")
                time.sleep(0.6)
    write_json(
        output / "manifest.json",
        dict(
            version="nse_historical_members_v1",
            files=rows,
            protocol_sha256=sha256(output / "protocol.json"),
            requests_sha256=sha256(output / "requests.jsonl"),
            identities_sha256=sha256(output / "identities.json"),
            complete=True,
        ),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("identities", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    collect(args.identities, args.output)
