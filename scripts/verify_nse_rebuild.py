"""Read-only checks of rebuilt membership/calendar/cohort and public provenance."""

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from helios.data.equities import sha256, write_json
from helios.equities.rebuild import membership, verified_file


def verify(snapshot: Path, output: Path) -> None:
    manifest = json.loads((snapshot / "manifest.json").read_text())
    assert manifest["version"] == "nse_public_minutes_v2" and manifest["complete"]
    for name, key in (
        ("protocol.json", "protocol_sha256"),
        ("sessions.json", "sessions_sha256"),
        ("universe.json", "universe_sha256"),
        ("session_checks.json", "checks_sha256"),
    ):
        verified_file(snapshot, name, manifest[key])
    protocol = json.loads((snapshot / "protocol.json").read_text())
    assert sha256(snapshot / "builder_source.py") == protocol["builder_sha256"]
    calendar = json.loads((snapshot / "sessions.json").read_text())
    universe = json.loads((snapshot / "universe.json").read_text())
    assert [r["day"] for r in universe] == list(calendar)
    assert all(len(r["members"]) in (50, 51) for r in universe)
    assert all("BSE" not in r["members"] for r in universe)
    assert calendar["2025-02-01"]["slots"] == calendar["2026-02-01"]["slots"] == 375
    assert calendar["2025-10-21"]["slots"] == 60
    checks = json.loads((snapshot / "session_checks.json").read_text())
    index = {(r["symbol"], r["day"]): r for r in checks}
    assert len(index) == len(checks)
    counts = Counter(r["status"] for r in checks)
    assert all(manifest["counts"][key] == value for key, value in counts.items())
    rows = screened = 0
    per_company = []
    special = Counter()
    for record in manifest["files"]:
        path = verified_file(snapshot, record["path"], record["sha256"])
        frame = pd.read_parquet(path)
        assert len(frame) == record["rows"]
        assert int(frame.research_eligible.sum()) == record["eligible_rows"]
        assert set(frame.symbol) == {record["symbol"]}
        assert not frame.open_time.duplicated().any()
        assert frame.close.equals(frame.source_close) and frame.volume.equals(frame.source_volume)
        assert np.isfinite(frame[["open", "high", "low", "close", "volume"]]).all().all()
        assert frame.session_date.between("2025-01-01", "2026-06-30").all()
        local = frame.timestamp.dt.tz_convert("Asia/Kolkata")
        assert frame.session_date.equals(local.dt.strftime("%Y-%m-%d"))
        assert (frame.available_at - frame.timestamp == pd.Timedelta(minutes=1)).all()
        for day, part in frame.groupby("session_date"):
            assert membership(record["symbol"], day)[1]
            setting = calendar[day]
            observed = part.timestamp.dt.tz_convert("Asia/Kolkata")
            minutes = observed.dt.hour * 60 + observed.dt.minute
            assert minutes.between(
                setting["open_minute"], setting["open_minute"] + setting["slots"] - 1
            ).all()
            assert set(part.screen_status) == {index[(record["symbol"], day)]["status"]}
            if part.research_eligible.any():
                assert part.research_eligible.all() and len(part) == setting["slots"]
                assert set(part.screen_status) == {"PASS_SCALE_SCREEN"}
                assert (part.volume > 0).all() and set(part.official_isin) == {record["isin"]}
            if setting["kind"] != "normal":
                special[day] += len(part)
        rows += len(frame)
        screened += record["eligible_rows"]
        per_company.append(
            dict(symbol=record["symbol"], rows=len(frame), screened_rows=record["eligible_rows"])
        )
    assert rows == manifest["rows"] and screened == manifest["eligible_rows"]
    assert not manifest["g7_eligible"] and not manifest["test_access"]
    write_json(
        output,
        dict(
            version="nse_rebuild_verification_v1",
            manifest_sha256=sha256(snapshot / "manifest.json"),
            rows=rows,
            screened_rows=screened,
            companies=len(manifest["files"]),
            screened_companies=sum(r["screened_rows"] > 0 for r in per_company),
            sessions=len(calendar),
            full_sessions=sum(s["slots"] == 375 for s in calendar.values()),
            short_sessions=sum(s["slots"] == 60 for s in calendar.values()),
            special_session_bars=dict(special),
            session_statuses=dict(counts),
            per_company=per_company,
            outside_membership_minutes_removed=manifest["counts"][
                "outside_membership_minutes_removed"
            ],
            source_units_unchanged=True,
            no_dummy_price_execution=True,
            test_access=False,
            g7_eligible=False,
            builder_source_sha256=protocol["builder_sha256"],
            retained_builder_modules={
                p.name: sha256(p) for p in (snapshot / "source").glob("*.py")
            },
        ),
    )
    print(f"Verified {rows:,} retained / {screened:,} screened rows", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    verify(args.snapshot, args.output)
