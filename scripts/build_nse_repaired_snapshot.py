"""Build an exclusive v2 conditional cohort; preserve v1 and quarantine unknown units."""

import argparse
import json
import shutil
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from helios.data.equities import constituents, sha256, write_json
from helios.equities.rebuild import (
    END,
    START,
    TEMPORARY,
    membership,
    parse_reviewed_candles,
    schedule,
    verified_file,
    verify_price_day,
)
from helios.equities.validation import bhavcopy, corporate_events, verified_references


def collection(root):
    manifest = json.loads((root / "manifest.json").read_text())
    for name, suffix in (("protocol", ".json"), ("requests", ".jsonl")):
        verified_file(root, name + suffix, manifest[name + "_sha256"])
    journal = [json.loads(r) for r in (root / "requests.jsonl").read_text().splitlines()]
    rows = manifest.get("sources", manifest.get("files"))
    if not manifest["complete"] or journal != rows:
        raise ValueError("incomplete collection or changed journal")
    for row in rows:
        if "sha256" in row:
            verified_file(root, row["path"], row["sha256"])
    return rows


def build(original, references, rebuilt_references, historical, output):
    manifest = json.loads((original / "manifest.json").read_text())
    for name, key in (
        ("protocol.json", "protocol_sha256"),
        ("requests.jsonl", "requests_sha256"),
        ("constituents.csv", "universe_sha256"),
    ):
        verified_file(original, name, manifest[key])
    roster = constituents((original / "constituents.csv").read_bytes())
    identity_rows = json.loads((historical / "identities.json").read_text())
    extra_manifest = json.loads((historical / "manifest.json").read_text())
    verified_file(historical, "identities.json", extra_manifest["identities_sha256"])
    members = {r["Symbol"]: r["ISIN Code"] for r in roster}
    members.update({r["symbol"]: r["isin"] for r in identity_rows})
    facts = json.loads(Path("configs/equities/validation_reference_v1.json").read_text())
    descriptor = json.loads((original / "calendar.json").read_text())
    raw_calendar = verified_file(original, descriptor["path"], descriptor["sha256"])
    holidays = set(facts["normal_weekday_holidays_2025"])
    holidays.update(
        datetime.strptime(r["tradingDate"], "%d-%b-%Y").date().isoformat()
        for r in json.loads(raw_calendar.read_text())["CM"]
    )
    sessions = schedule(holidays)
    refs = [
        (references, list(verified_references(references).values())),
        (rebuilt_references, collection(rebuilt_references)),
    ]
    daily = {}
    capital_symbols = set()
    for root, rows in refs:
        for row in rows:
            if row["key"].startswith("actions_") and row["status"] == 200:
                events = corporate_events(
                    (root / row["path"]).read_bytes(),
                    row["key"][8:],
                    date.fromisoformat(START),
                    date.fromisoformat(END),
                )
                capital_symbols.update(e["symbol"] for e in events if e["kind"] != "dividend")
            if row["key"].startswith("bhav_") and row["status"] == 200:
                day = row["key"][5:]
                frame = bhavcopy((root / row["path"]).read_bytes(), date.fromisoformat(day))
                daily[day] = frame.loc[frame.TckrSymb.isin(set(members) | {"ZOMATO", "TATAMOTORS"})]
    sources = defaultdict(list)
    for root, rows in (
        (
            original,
            [json.loads(line) for line in (original / "requests.jsonl").read_text().splitlines()],
        ),
        (historical, collection(historical)),
    ):
        for row in rows:
            if row.get("kind") == "actions":
                if row["status"] != 200:
                    capital_symbols.add(row["symbol"])
                else:
                    events = corporate_events(
                        (root / row["path"]).read_bytes(),
                        row["symbol"],
                        date.fromisoformat(START),
                        date.fromisoformat(END),
                    )
                    capital_symbols.update(e["symbol"] for e in events if e["kind"] != "dividend")
                continue
            if "sha256" in row:
                path = verified_file(root, row["path"], row["sha256"])
                sources[row["symbol"]].append((path, row))
    output.mkdir(parents=True, exist_ok=False)
    (output / "bars").mkdir()
    shutil.copyfile(__file__, output / "builder_source.py")
    (output / "source").mkdir()
    for name in ("rebuild.py", "validation.py"):
        shutil.copyfile(Path("research/helios/equities") / name, output / "source" / name)
    write_json(
        output / "protocol.json",
        dict(
            version="nse_public_minutes_v2",
            start=START,
            end=END,
            source_prices="Unchanged provider OHLCV; no synthetic raw-unit inversion",
            price_screen="Fixed 0.2% daily extreme scale screen; no minute/volume certification",
            cohort="Historical membership; complete positive-volume scale-screened days",
            test_prices_requested=False,
            g7_eligible=False,
            original_manifest_sha256=sha256(original / "manifest.json"),
            reference_manifest_sha256=sha256(references / "manifest.json"),
            rebuild_reference_manifest_sha256=sha256(rebuilt_references / "manifest.json"),
            historical_manifest_sha256=sha256(historical / "manifest.json"),
            builder_sha256=sha256(Path(__file__)),
        ),
    )
    write_json(output / "sessions.json", sessions)
    universe = []
    for day in sessions:
        active = [s for s in sorted(members) if membership(s, day)[0]]
        tradable = [s for s in active if membership(s, day)[1]]
        temporary = [s for s in active if s in TEMPORARY]
        if len(active) != 50 + len(temporary):
            raise ValueError("reconstructed baseline does not contain 50 members: " + day)
        universe.append(
            dict(
                day=day,
                members=active,
                tradable=tradable,
                dummy_unlisted=sorted(set(active) - set(tradable)),
            )
        )
    write_json(output / "universe.json", universe)
    files, checks = [], []
    counts = Counter()
    for symbol, isin in sorted(members.items()):
        chunks = []
        for path, row in sources[symbol]:
            frame = parse_reviewed_candles(
                path.read_bytes(), symbol, row["start"], row["end"], sessions
            )
            if not frame.empty:
                chunks.append(frame)
        if not chunks:
            continue
        frame = pd.concat(chunks).sort_values("open_time").reset_index(drop=True)
        if frame.open_time.duplicated().any():
            raise ValueError("overlapping historical responses: " + symbol)
        in_universe = frame.session_date.map(lambda day, symbol=symbol: membership(symbol, day)[1])
        counts["outside_membership_minutes_removed"] += int((~in_universe).sum())
        frame = frame.loc[in_universe].copy()
        if frame.empty:
            continue
        statuses, asof_symbols, asof_isins = {}, {}, {}
        for day, setting in sessions.items():
            if not membership(symbol, day)[1]:
                continue
            part = frame.loc[frame.session_date == day]
            reference = daily.get(day)
            found = pd.DataFrame() if reference is None else reference.loc[reference.ISIN == isin]
            if found.empty and reference is not None:
                aliases = {symbol} | ({"ZOMATO"} if symbol == "ETERNAL" else set())
                aliases |= {"TATAMOTORS"} if symbol == "TMPV" else set()
                found = reference.loc[reference.TckrSymb.isin(aliases)]
            status = "NO_DAILY_IDENTITY_REFERENCE"
            if len(found) == 1:
                official = found.iloc[0]
                asof_symbols[day], asof_isins[day] = official.TckrSymb, official.ISIN
                status = verify_price_day(part, official, symbol)
                if symbol in capital_symbols:
                    status = "UNRESOLVED_CAPITAL_ACTION_UNITS"
                if status == "PASS_SCALE_SCREEN" and str(official.ISIN) != isin:
                    status = "UNVERIFIED_ISIN_CONTINUITY"
            if status == "PASS_SCALE_SCREEN":
                if len(part) != setting["slots"]:
                    status = "INCOMPLETE_SESSION"
                elif (part.volume <= 0).any():
                    status = "ZERO_VOLUME_SESSION"
            statuses[day] = status
            counts[status] += 1
            checks.append(
                dict(
                    symbol=symbol,
                    day=day,
                    status=status,
                    rows=len(part),
                    expected_rows=setting["slots"],
                    official_symbol=asof_symbols.get(day),
                    official_isin=asof_isins.get(day),
                )
            )
        frame["research_eligible"] = frame.session_date.map(statuses) == "PASS_SCALE_SCREEN"
        frame["screen_status"] = frame.session_date.map(statuses)
        frame["official_symbol"] = frame.session_date.map(asof_symbols)
        frame["official_isin"] = frame.session_date.map(asof_isins)
        path = output / "bars" / (symbol + ".parquet")
        frame.to_parquet(path, index=False)
        files.append(
            dict(
                symbol=symbol,
                isin=isin,
                path=str(path.relative_to(output)),
                sha256=sha256(path),
                rows=len(frame),
                eligible_rows=int(frame.research_eligible.sum()),
                expected_valid_sessions=[
                    d for d in sessions if d >= "2026-01-09" and membership(symbol, d)[1]
                ],
            )
        )
        print(symbol, len(frame), int(frame.research_eligible.sum()), flush=True)
    write_json(output / "session_checks.json", checks)
    write_json(
        output / "manifest.json",
        dict(
            version="nse_public_minutes_v2",
            files=files,
            complete=True,
            protocol_sha256=sha256(output / "protocol.json"),
            sessions_sha256=sha256(output / "sessions.json"),
            universe_sha256=sha256(output / "universe.json"),
            checks_sha256=sha256(output / "session_checks.json"),
            counts=dict(counts),
            rows=sum(r["rows"] for r in files),
            eligible_rows=sum(r["eligible_rows"] for r in files),
            g7_eligible=False,
            test_access=False,
        ),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("original", "references", "rebuilt_references", "historical", "output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    build(args.original, args.references, args.rebuilt_references, args.historical, args.output)
