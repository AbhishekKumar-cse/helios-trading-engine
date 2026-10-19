"""Extract retrospective official identity/price-basis regimes without adjusting prices."""

import argparse
import json
from collections import defaultdict
from pathlib import Path

from helios.data.equities import sha256, write_json


def report(certificate_path, output):
    if output.exists():
        raise ValueError("identity evidence must not be overwritten")
    certificate = json.loads(certificate_path.read_text())
    full = Path(certificate["report_path"])
    if sha256(full) != certificate["report_sha256"]:
        raise ValueError("certification detail hash mismatch")
    detail = json.loads(full.read_text())
    rows = defaultdict(list)
    for row in detail["daily_comparisons"]:
        rows[row["symbol"]].append(row)
    companies = []
    for company in certificate["companies"]:
        if company["screened_rows"]:
            continue
        segments = []
        for row in sorted(rows[company["symbol"]], key=lambda r: r["day"]):
            if row["status"] != "DIAGNOSTIC_ONLY":
                continue
            shifted = (
                min(row["high_ratio"], row["low_ratio"]) > 1.05
                or max(row["high_ratio"], row["low_ratio"]) < 0.95
            )
            identity = (row["official_isin"], shifted)
            if (
                not segments
                or (segments[-1]["isin"], segments[-1]["large_scale_shift"]) != identity
            ):
                segments.append(
                    dict(
                        isin=identity[0],
                        large_scale_shift=shifted,
                        first_observed_day=row["day"],
                        last_observed_day=row["day"],
                        observations=0,
                        min_extreme_ratio=min(row["high_ratio"], row["low_ratio"]),
                        max_extreme_ratio=max(row["high_ratio"], row["low_ratio"]),
                    )
                )
            segment = segments[-1]
            segment["observations"] += 1
            segment["last_observed_day"] = row["day"]
            segment["min_extreme_ratio"] = min(
                segment["min_extreme_ratio"], row["high_ratio"], row["low_ratio"]
            )
            segment["max_extreme_ratio"] = max(
                segment["max_extreme_ratio"], row["high_ratio"], row["low_ratio"]
            )
        companies.append(
            dict(
                symbol=company["symbol"],
                official_daily_regimes=segments,
                retained_official_action_records=company["capital_events"],
                raw_minute_units_certified=False,
                point_in_time_availability_certified=False,
            )
        )
    write_json(
        output,
        dict(
            version="nse_retrospective_identity_evidence_v1",
            companies=companies,
            certificate_sha256=sha256(certificate_path),
            detail_sha256=sha256(full),
            scope=(
                "Observed EQ identities and broad price-basis shifts only; "
                "not share-factor repairs."
            ),
            limitations=[
                (
                    "Segment dates are observed dates, not certified legal "
                    "or announcement effective times."
                ),
                (
                    "No EQ reference for temporary BE listings. "
                    "Missing member-days are not interpolated."
                ),
                (
                    "No inverse scaling, eligibility change, TEST access "
                    "or certificate of minute/volume units."
                ),
            ],
        ),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--certificate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report(args.certificate, args.output)
