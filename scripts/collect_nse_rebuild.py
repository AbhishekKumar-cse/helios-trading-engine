"""Collect bounded, public reconstruction evidence; retain refusals without bypass."""

import argparse
import io
import json
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path
from zipfile import ZipFile

import pandas as pd
from collect_nse_validation import retain

from helios.data.equities import sha256, write_json
from helios.equities.validation import bhavcopy, verified_references

NOTICES = {
    "itc_inclusion": "ind_prs30122024.pdf",
    "tata_inclusion": "ind_prs07102025.pdf",
    "tata_exclusion": "ind_prs13112025.pdf",
    "hul_inclusion": "ind_prs28112025.pdf",
    "hul_exclusion": "ind_prs20022026_1.pdf",
    "review_202409": "ind_prs23082024.pdf",
}


def collect(original: Path, references: Path, output: Path) -> None:
    old = verified_references(references)
    output.mkdir(parents=True, exist_ok=False)
    (output / "raw").mkdir()
    shutil.copyfile(__file__, output / "collector_source.py")
    write_json(
        output / "protocol.json",
        dict(
            version="nse_rebuild_reference_v1",
            start="2025-01-01",
            end="2026-06-30",
            test_prices_requested=False,
            collector_sha256=sha256(Path(__file__)),
            reference_manifest_sha256=sha256(references / "manifest.json"),
            purpose="Daily session references, historical identities and membership notices",
        ),
    )
    rows = []
    with (output / "requests.jsonl").open("x") as journal:

        def request(key: str, url: str) -> None:
            record = retain(url, output / "raw" / (key + ".raw"))
            record.update(key=key, path="raw/" + record["path"])
            rows.append(record)
            journal.write(json.dumps(record) + "\n")
            journal.flush()
            print(key, record["status"], flush=True)

        for key, suffix in NOTICES.items():
            request(key, "https://www.niftyindices.com/Press_Release/" + suffix)
        facts = json.loads(Path("configs/equities/validation_reference_v1.json").read_text())
        holidays = set(facts["normal_weekday_holidays_2025"])
        payload = json.loads((original / "nse_holidays_raw.json").read_text())
        holidays.update(
            datetime.strptime(r["tradingDate"], "%d-%b-%Y").date().isoformat()
            for r in payload["CM"]
        )
        special = {"2025-02-01", "2026-02-01", "2025-10-21"}
        day = date(2025, 1, 1)
        while day <= date(2026, 6, 30):
            key = "bhav_" + day.isoformat()
            if (day.weekday() < 5 and day.isoformat() not in holidays) or str(day) in special:
                if key not in old or old[key]["status"] != 200:
                    request(
                        key,
                        "https://nsearchives.nseindia.com/content/cm/"
                        f"BhavCopy_NSE_CM_0_0_0_{day:%Y%m%d}_F_0000.csv.zip",
                    )
            day += timedelta(days=1)
    write_json(
        output / "manifest.json",
        dict(
            version="nse_rebuild_reference_v1",
            sources=rows,
            protocol_sha256=sha256(output / "protocol.json"),
            requests_sha256=sha256(output / "requests.jsonl"),
            complete=True,
        ),
    )
    resolve_identities(references, output)


def resolve_identities(references: Path, output: Path) -> None:
    old = verified_references(references)
    from build_nse_repaired_snapshot import collection

    rows = collection(output)
    shutil.copyfile(__file__, output / "identity_resolver_source.py")
    identities = []
    for symbol, first, last in [
        ("WIPRO", "2025-01-01", "2026-06-30"),
        ("BPCL", "2025-01-01", "2025-03-27"),
        ("BRITANNIA", "2025-01-01", "2025-03-27"),
        ("HEROMOTOCO", "2025-01-01", "2025-09-29"),
        ("INDUSINDBK", "2025-01-01", "2025-09-29"),
        ("ITCHOTELS", "2025-01-29", "2025-02-07"),
        ("TMCV", "2025-11-12", "2025-11-14"),
        ("KWIL", "2026-02-16", "2026-02-23"),
    ]:
        sample = (
            "2025-01-07"
            if symbol in {"WIPRO", "BPCL", "BRITANNIA", "HEROMOTOCO", "INDUSINDBK"}
            else first
        )
        key = "bhav_" + sample
        row = old.get(key) or next(r for r in rows if r["key"] == key)
        root = references if key in old else output
        body = (root / row["path"]).read_bytes()
        frame = bhavcopy(body, date.fromisoformat(sample))
        if symbol not in set(frame.TckrSymb):
            # Newly listed demerged securities may begin in trade-for-trade BE.
            # Resolve identity without silently treating that series as EQ execution.
            with ZipFile(io.BytesIO(body)) as archive:
                if len(archive.namelist()) != 1:
                    raise ValueError("ambiguous reference archive")
                frame = pd.read_csv(archive.open(archive.namelist()[0]), keep_default_na=False)
            if set(frame.TradDt) != {sample}:
                raise ValueError("historical identity reference date changed")
        found = frame.loc[frame.TckrSymb == symbol]
        if len(found) != 1:
            raise ValueError("historical identity is missing or ambiguous: " + symbol)
        identities.append(
            dict(
                symbol=symbol,
                isin=found.ISIN.iloc[0],
                start=first,
                end=last,
                listing_series=found.SctySrs.iloc[0],
                reference=key,
                reference_sha256=row["sha256"],
            )
        )
    write_json(output / "historical_identities.json", identities)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path)
    parser.add_argument("references", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--resolve-only", action="store_true")
    args = parser.parse_args()
    if args.resolve_only:
        resolve_identities(args.references, args.output)
    else:
        collect(args.original, args.references, args.output)
