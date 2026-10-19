"""Produce an evidence-bound certification verdict, including explicit refusals.

Daily extremes and volumes are diagnostics, never a reconstruction of raw minute
units. Reads only the retained TRAIN/VALID prefix; no network or TEST access.
"""

import argparse
import json
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from helios.data.equities import sha256, write_json
from helios.equities.rebuild import END, START, verified_file
from helios.equities.validation import bhavcopy, corporate_events, verified_references


def collection(root):
    manifest = json.loads((root / "manifest.json").read_text())
    if not manifest["complete"]:
        raise ValueError("incomplete reference collection")
    for name, suffix in (("protocol", ".json"), ("requests", ".jsonl")):
        verified_file(root, name + suffix, manifest[name + "_sha256"])
    rows = manifest.get("sources", manifest.get("files"))
    if rows != [json.loads(r) for r in (root / "requests.jsonl").read_text().splitlines()]:
        raise ValueError("reference journal differs from manifest")
    for row in rows:
        verified_file(root, row["path"], row["sha256"])
    return rows


def certify(snapshot, references, rebuilt_references, historical, output, summary_path):
    if output.exists() or summary_path.exists():
        raise ValueError("certification reports are exclusive immutable artifacts")
    manifest = json.loads((snapshot / "manifest.json").read_text())
    if (
        manifest["version"] != "nse_public_minutes_v2"
        or not manifest["complete"]
        or manifest["g7_eligible"]
        or manifest["test_access"]
    ):
        raise ValueError("expected the conditional v2 TRAIN/VALID snapshot")
    for name, key in (
        ("protocol.json", "protocol_sha256"),
        ("session_checks.json", "checks_sha256"),
        ("sessions.json", "sessions_sha256"),
        ("universe.json", "universe_sha256"),
    ):
        verified_file(snapshot, name, manifest[key])
    protocol = json.loads((snapshot / "protocol.json").read_text())
    for root, key in (
        (references, "reference_manifest_sha256"),
        (rebuilt_references, "rebuild_reference_manifest_sha256"),
        (historical, "historical_manifest_sha256"),
    ):
        if sha256(root / "manifest.json") != protocol[key]:
            raise ValueError("certification references differ from snapshot lineage")
    sources, daily, actions = [], {}, defaultdict(list)
    for root, rows in (
        (references, list(verified_references(references).values())),
        (rebuilt_references, collection(rebuilt_references)),
        (historical, collection(historical)),
    ):
        for row in rows:
            sources.append(dict(root=str(root), **row))
            if row["status"] != 200:
                continue
            key = row.get("key", "")
            if key.startswith("bhav_"):
                day = key[5:]
                daily[day] = bhavcopy((root / row["path"]).read_bytes(), date.fromisoformat(day))
            if key.startswith("actions_") or row.get("kind") == "actions":
                symbol = key[8:] if key else row["symbol"]
                actions[symbol] = corporate_events(
                    (root / row["path"]).read_bytes(),
                    symbol,
                    date.fromisoformat(START),
                    date.fromisoformat(END),
                )
    checks = json.loads((snapshot / "session_checks.json").read_text())
    per_company, comparisons = [], []
    for item in manifest["files"]:
        symbol = item["symbol"]
        frame = pd.read_parquet(verified_file(snapshot, item["path"], item["sha256"]))
        if not frame.session_date.between(START, END).all():
            raise ValueError("certification refuses observations outside TRAIN/VALID")
        official_isins, volume_ratios, extreme_errors = set(), [], []
        for day, minute in frame.groupby("session_date", sort=True):
            official = daily[day]
            aliases = {symbol} | ({"ZOMATO"} if symbol == "ETERNAL" else set())
            matched = official.loc[official.TckrSymb.isin(aliases)]
            if len(matched) != 1:
                comparisons.append(dict(symbol=symbol, day=day, status="NO_UNIQUE_EQ_REFERENCE"))
                continue
            row = matched.iloc[0]
            official_isins.add(row.ISIN)
            high_ratio, low_ratio = minute.high.max() / row.HghPric, minute.low.min() / row.LwPric
            volume_ratio = (
                None if row.TtlTradgVol == 0 else float(minute.volume.sum() / row.TtlTradgVol)
            )
            extreme_errors.append(float(max(abs(high_ratio - 1), abs(low_ratio - 1))))
            if volume_ratio is not None:
                volume_ratios.append(volume_ratio)
            comparisons.append(
                dict(
                    symbol=symbol,
                    day=day,
                    status="DIAGNOSTIC_ONLY",
                    official_isin=row.ISIN,
                    high_ratio=float(high_ratio),
                    low_ratio=float(low_ratio),
                    minute_volume=float(minute.volume.sum()),
                    official_volume=int(row.TtlTradgVol),
                    volume_ratio=volume_ratio,
                )
            )
        statuses = Counter(r["status"] for r in checks if r["symbol"] == symbol)
        events = actions.get(symbol)
        per_company.append(
            dict(
                symbol=symbol,
                rows=len(frame),
                screened_rows=item["eligible_rows"],
                checks=dict(statuses),
                official_daily_isins=sorted(official_isins),
                action_query_available=events is not None,
                capital_events=[]
                if events is None
                else [e for e in events if e["kind"] != "dividend"],
                raw_minute_unit_certified=False,
                minute_volume_unit_certified=False,
                announcement_availability_certified=False,
                daily_extreme_max_relative_difference=max(extreme_errors, default=None),
                minute_to_daily_volume_ratio_range=(
                    None if not volume_ratios else [min(volume_ratios), max(volume_ratios)]
                ),
                verdict="BLOCKED" if not item["eligible_rows"] else "CONDITIONAL_SCREEN_ONLY",
            )
        )
    obligations = [
        dict(
            id="raw_units",
            status="MISSING",
            required=(
                "Independent raw minute price/volume vintage and dated adjustment/ISIN chain. "
                "A rounded adjusted price cannot be inverted exactly using a share ratio."
            ),
        ),
        dict(
            id="causal_availability",
            status="MISSING",
            required=(
                "Contemporaneous membership/action/calendar publication times "
                "and causal outage handling."
            ),
        ),
        dict(
            id="costs",
            status="SCENARIO_ONLY",
            required=(
                "Dated account tariff/contract-note reconciliation; "
                "present v2 taxes are a reference estimate."
            ),
        ),
        dict(
            id="execution",
            status="MISSING",
            required=(
                "Timestamped executable spread/depth, latency and participation/fill calibration. "
                "OHLCV and public last trade do not prove executable liquidity or 5bps slippage."
            ),
        ),
    ]
    report = dict(
        version="nse_execution_certification_v1",
        assessed_at=datetime.now(UTC).isoformat(),
        verdict="NOT_CERTIFIED",
        g7_eligible=False,
        test_access=False,
        snapshot_manifest_sha256=sha256(snapshot / "manifest.json"),
        obligations=obligations,
        companies=per_company,
        diagnostic_scope=(
            "Daily regular/preopen scope differs; volume equality is not required or proof."
        ),
        sources=sources,
        daily_comparisons=comparisons,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json(output, report)
    write_json(
        summary_path,
        {key: value for key, value in report.items() if key not in ("sources", "daily_comparisons")}
        | dict(
            report_path=str(output),
            report_sha256=sha256(output),
            diagnostic_stock_days=len(comparisons),
            official_reference_sessions=len(daily),
            independently_certified_companies=0,
        ),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--references", type=Path, required=True)
    parser.add_argument("--rebuilt-references", type=Path, required=True)
    parser.add_argument("--historical", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    certify(
        args.snapshot,
        args.references,
        args.rebuilt_references,
        args.historical,
        args.output,
        args.summary,
    )
