"""Register the RELIANCE PAPER benchmark from one retained public instrument dump."""

import gzip
import hashlib
import json
import urllib.request
from dataclasses import asdict
from datetime import UTC, datetime

from sqlalchemy import text

from helios.common.db import get_engine
from helios.common.lineage import PROJECT_ROOT
from helios.data.equities import sha256, write_json
from helios.equities.instruments import public_instrument


def main():
    started = datetime.now(UTC)
    directory = PROJECT_ROOT / "reports_out/equity_instruments" / started.strftime("%Y%m%dT%H%M%SZ")
    directory.mkdir(parents=True, exist_ok=False)
    url = "https://api.kite.trade/instruments/NSE"
    request = urllib.request.Request(
        url, headers={"X-Kite-Version": "3", "User-Agent": "HELIOS academic research"}
    )
    # No auth, account, quote or order endpoints. 401/403 is terminal.
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
    (directory / "response.bin").write_bytes(raw)
    payload = gzip.decompress(raw) if raw.startswith(b"\x1f\x8b") else raw
    selected = public_instrument(payload, "RELIANCE")
    snapshot = PROJECT_ROOT / "data/equities/nifty50_minutes/20261017_public_round1"
    manifest = json.loads((snapshot / "manifest.json").read_text())
    record = next(r for r in manifest["files"] if r["symbol"] == selected.symbol)
    proof = dict(
        version="nse_current_instrument_source_v1",
        captured_at=started.isoformat(),
        source_url=url,
        raw_path=str(directory / "response.bin"),
        raw_sha256=hashlib.sha256(raw).hexdigest(),
        source_manifest_sha256=sha256(snapshot / "manifest.json"),
        isin=record["isin"],
        selected=asdict(selected),
        first_observed_date=record["first_session"],
        historical_tick_sizes_verified=False,
        price_or_quote_observation=False,
    )
    write_json(directory / "source.json", proof)
    with get_engine().begin() as connection:
        connection.execute(
            text("""INSERT INTO instruments
            (symbol,venue,base_asset,quote_asset,tick_size,lot_size,first_available_date,active)
            VALUES (:symbol,'nse_cash',:symbol,'INR',:tick,:lot,:first,true)
            ON CONFLICT(symbol) DO NOTHING"""),
            dict(
                symbol=selected.symbol,
                tick=selected.tick_size,
                lot=selected.lot_size,
                first=record["first_session"],
            ),
        )
        row = (
            connection.execute(
                text(
                    "SELECT instrument_id,venue,quote_asset,tick_size,lot_size "
                    "FROM instruments WHERE symbol=:s"
                ),
                dict(s=selected.symbol),
            )
            .mappings()
            .one()
        )
        if (row["venue"], row["quote_asset"], row["tick_size"], row["lot_size"]) != (
            "nse_cash",
            "INR",
            selected.tick_size,
            selected.lot_size,
        ):
            raise ValueError("existing instrument differs; refuse a silent metadata update")
        connection.execute(
            text("""INSERT INTO audit_events
            (ts,actor,action,subject,after_hash,justification,payload)
            VALUES (:ts,'equity_metadata','NSE_INSTRUMENT_REGISTERED',:symbol,:hash,:why,
                    CAST(:payload AS jsonb))"""),
            dict(
                ts=int(started.timestamp() * 1_000_000),
                symbol=selected.symbol,
                hash=sha256(directory / "source.json"),
                why="Current public NSE cash metadata for integration-only PAPER; "
                "not historical tick validation",
                payload=json.dumps(proof | dict(instrument_id=row["instrument_id"]), default=str),
            ),
        )
    write_json(PROJECT_ROOT / "docs/research/nse_public_instrument_20261018.json", proof)
    print(
        json.dumps(
            dict(
                symbol=selected.symbol,
                tick_size=str(selected.tick_size),
                lot_size=str(selected.lot_size),
                source_sha256=proof["raw_sha256"],
            )
        )
    )


if __name__ == "__main__":
    main()
