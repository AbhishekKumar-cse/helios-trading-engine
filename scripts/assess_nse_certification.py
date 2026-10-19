"""Publish a hash-verified obligation assessment; never grant source eligibility.

Public documentation can resolve definitions and reference costs. It cannot
substitute for historical minute vintage, account invoices or executable quotes.
No price collection, TEST access, data repair, registry mutation or promotion.
"""

import argparse
import json
import shutil
import urllib.error
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from helios.data.equities import sha256, write_json
from helios.equities.rebuild import verified_file

SOURCES = {
    "provider_candle_definition": "https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/",
    "exchange_order_trade_product": "https://www.nseindia.com/static/market-data/eod-historical-data-subscription",
    "exchange_statutory_levies": "https://www.nseindia.com/static/invest/first-time-investor-sebi-turnover-fees-stt-other-levies",
    "broker_reference_scenario": "https://zerodha.com/charges/",
}


def assess(certificate: Path, snapshot: Path, output: Path) -> None:
    if output.exists():
        raise ValueError("assessment needs a new immutable output directory")
    summary = json.loads(certificate.read_text())
    detail_path = Path(summary["report_path"])
    if sha256(detail_path) != summary["report_sha256"]:
        raise ValueError("certification detail checksum mismatch")
    detail = json.loads(detail_path.read_text())
    if sha256(snapshot / "manifest.json") != detail["snapshot_manifest_sha256"]:
        raise ValueError("certification describes another snapshot")
    manifest = json.loads((snapshot / "manifest.json").read_text())
    if manifest["test_access"] or manifest["g7_eligible"] or not manifest["complete"]:
        raise ValueError("expected conditional TEST-sealed source")
    for name, key in (
        ("protocol.json", "protocol_sha256"),
        ("sessions.json", "sessions_sha256"),
        ("session_checks.json", "checks_sha256"),
        ("universe.json", "universe_sha256"),
    ):
        verified_file(snapshot, name, manifest[key])
    for source in detail["sources"]:
        verified_file(Path(source["root"]), source["path"], source["sha256"])
    checked_files = []
    for record in manifest["files"]:
        path = verified_file(snapshot, record["path"], record["sha256"])
        checked_files.append(
            dict(
                symbol=record["symbol"],
                path=record["path"],
                sha256=sha256(path),
                bytes=path.stat().st_size,
            )
        )
    output.mkdir(parents=True, exist_ok=False)
    from helios.common.lineage import PROJECT_ROOT, git_commit, git_is_dirty

    source_hashes = {}
    for source in (
        Path(__file__).resolve(),
        PROJECT_ROOT / "research/helios/data/equities.py",
        PROJECT_ROOT / "research/helios/equities/rebuild.py",
    ):
        relative = source.relative_to(PROJECT_ROOT)
        target = output / "source" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        if sha256(source) != sha256(target):
            raise ValueError("assessment source changed while archiving")
        source_hashes[str(relative)] = sha256(target)
    receipts = []
    for key, url in SOURCES.items():
        status, error = None, None
        try:
            with urllib.request.urlopen(url, timeout=20) as response:
                status = response.status
                body = response.read(5_000_001)
            if len(body) > 5_000_000:
                raise ValueError("documentation response exceeds bound")
        except urllib.error.HTTPError as exc:
            status, body, error = exc.code, exc.read(100_000), "HTTP refusal; no retry or bypass"
        except Exception as exc:
            body, error = b"", type(exc).__name__
        path = output / (key + ".html")
        path.write_bytes(body)
        receipts.append(
            dict(
                key=key,
                url=url,
                checked_at=datetime.now(UTC).isoformat(),
                status=status,
                error=error,
                path=path.name,
                sha256=sha256(path),
                establishes="reference documentation only; not historical execution certification",
            )
        )
    companies = []
    for item in detail["companies"]:
        flags = [
            "raw_minute_unit_certified",
            "minute_volume_unit_certified",
            "announcement_availability_certified",
        ]
        companies.append(
            dict(
                symbol=item["symbol"],
                screened_rows=item["screened_rows"],
                source_status=item["verdict"],
                official_daily_isins=item["official_daily_isins"],
                capital_events=item["capital_events"],
                action_broadcast_fields_present=sum(
                    bool(e.get("broadcast")) for e in item["capital_events"]
                ),
                verified_claims={key: item[key] for key in flags},
                daily_extreme_max_relative_difference=item["daily_extreme_max_relative_difference"],
                minute_to_daily_volume_ratio_range=item["minute_to_daily_volume_ratio_range"],
                release_allowed=False,
                required_evidence=[
                    "Independent minute price/share/volume vintage and effective identity chain",
                    "Publication/receipt times and a causal outage/eligibility policy",
                    "Dated account tariff/contract notes and executable liquidity calibration",
                ],
            )
        )
    report = dict(
        version="nse_certification_obligations_v1",
        assessed_at=datetime.now(UTC).isoformat(),
        verdict="NOT_CERTIFIED",
        g7_eligible=False,
        test_access=False,
        certificate_sha256=sha256(certificate),
        detail_sha256=sha256(detail_path),
        snapshot_manifest_sha256=sha256(snapshot / "manifest.json"),
        verified_reference_bodies=len(detail["sources"]),
        diagnostic_stock_days=summary["diagnostic_stock_days"],
        official_reference_sessions=summary["official_reference_sessions"],
        source_status_counts=dict(Counter(r["source_status"] for r in companies)),
        obligations=detail["obligations"],
        companies=companies,
        documentation_receipts=receipts,
        source_release_count=0,
        source_commit=git_commit(),
        dirty=git_is_dirty(),
        source_hashes=source_hashes,
        verified_minute_files=checked_files,
        exclusions_changed=False,
        gates_changed=False,
        boundary=(
            "Public candle definitions and daily aggregates cannot establish exact raw-minute "
            "vintage, contemporaneous availability, historical account acceptance or fills. "
            "This assessment records verified evidence and specific unresolved obligations."
        ),
    )
    write_json(output / "assessment.json", report)
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "verdict",
                    "source_status_counts",
                    "source_release_count",
                    "verified_reference_bodies",
                )
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--certificate", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assess(args.certificate, args.snapshot, args.output)
