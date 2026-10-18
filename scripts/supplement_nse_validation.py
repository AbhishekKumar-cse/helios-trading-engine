"""Retain additional reviewed reference documents in a new immutable directory."""

import argparse
from pathlib import Path

from collect_nse_validation import retain

from helios.data.equities import write_json

URLS = {
    "budget_session_2025": "https://nsearchives.nseindia.com/content/circulars/CMTR65729.pdf",
    "muhurat_session_2025": "https://nsearchives.nseindia.com/content/circulars/CMTR70319.pdf",
    "holidays_2025": "https://nsearchives.nseindia.com/content/circulars/CMTR65587.pdf",
    "holidays_2026_initial": "https://nsearchives.nseindia.com/content/circulars/CMTR71775.pdf",
    "stt_methodology": "https://nsearchives.nseindia.com/content/circulars/cmtr5588.htm",
    "broker_stt": "https://support.zerodha.com/category/account-opening/resident-individual/ri-charges/articles/how-is-the-securities-transaction-tax-stt-calculated",
}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    rows = []
    for key, url in URLS.items():
        row = retain(url, args.output / (key + ".raw"))
        row["key"] = key
        rows.append(row)
        print(key, row["status"], flush=True)
    write_json(
        args.output / "manifest.json", dict(version="nse_validation_supplement_v1", sources=rows)
    )
