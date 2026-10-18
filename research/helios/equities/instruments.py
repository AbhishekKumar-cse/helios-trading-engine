"""Parse current NSE cash instrument metadata; never use dump prices as live quotes."""

import csv
import io
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class NseInstrument:
    symbol: str
    name: str
    tick_size: Decimal
    lot_size: Decimal
    instrument_token: str
    exchange_token: str


def public_instrument(raw: bytes, symbol: str) -> NseInstrument:
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    matches = [
        r
        for r in rows
        if r.get("tradingsymbol") == symbol
        and r.get("exchange") == r.get("segment") == "NSE"
        and r.get("instrument_type") == "EQ"
    ]
    if len(matches) != 1:
        raise ValueError("one current NSE cash instrument must match the exact symbol")
    row = matches[0]
    tick, lot = Decimal(row["tick_size"]), Decimal(row["lot_size"])
    if not tick.is_finite() or tick <= 0 or lot != 1:
        raise ValueError("positive tick and whole-share lot required")
    if not row["instrument_token"].isdigit() or not row["exchange_token"].isdigit():
        raise ValueError("numeric source instrument identities required")
    return NseInstrument(
        symbol, row["name"], tick, lot, row["instrument_token"], row["exchange_token"]
    )
