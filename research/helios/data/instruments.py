"""Fill the `instruments` table from real sources (step 058).

Three facts are needed per coin, and none of them may be typed by hand:

- **tick size** (smallest price step) and **lot size** (smallest quantity step) come from
  Binance's exchange information API, so they match what the venue actually enforces;
- **first available date** comes from the bars already on disk, because what matters for
  research is the first day we *have data for*, not a listing date printed somewhere else;
- the coin list itself comes from `configs/universe.yaml`.

Writing is an upsert keyed on the symbol, so running the seed twice leaves the same five
rows rather than duplicates or errors.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import Connection, text

from helios.data.bars import DEFAULT_OUT_DIR, BarBuildError
from helios.data.binance import fetch_text
from helios.data.loader import first_open_time

EXCHANGE_INFO_URL = "https://api.binance.com/api/v3/exchangeInfo"
TRADING = "TRADING"


class InstrumentError(Exception):
    """Raised when exchange information is missing or does not look as expected."""


@dataclass(frozen=True)
class InstrumentSpec:
    """One tradable pair, ready to be written to the `instruments` table."""

    symbol: str
    base_asset: str
    quote_asset: str
    tick_size: Decimal
    lot_size: Decimal
    status: str
    first_available_date: date | None = None

    @property
    def active(self) -> bool:
        return self.status == TRADING


def exchange_info_url(symbols: list[str]) -> str:
    """Binance wants the symbol list as a JSON array inside the query string."""
    as_json = json.dumps(symbols, separators=(",", ":"))
    return f"{EXCHANGE_INFO_URL}?symbols={quote(as_json)}"


def _filter_value(filters: list[dict[str, str]], kind: str, field: str, symbol: str) -> Decimal:
    for entry in filters:
        if entry.get("filterType") == kind:
            try:
                return Decimal(entry[field])
            except (KeyError, ArithmeticError) as exc:
                raise InstrumentError(f"{symbol}: bad {field} in {kind}: {entry}") from exc
    raise InstrumentError(f"{symbol}: no {kind} in the exchange information")


def parse_exchange_info(
    payload: dict[str, object], symbols: list[str]
) -> dict[str, InstrumentSpec]:
    """Pick tick size, lot size and the assets out of Binance's answer."""
    entries = payload.get("symbols")
    if not isinstance(entries, list):
        raise InstrumentError("exchange information has no 'symbols' list")

    found: dict[str, InstrumentSpec] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        symbol = str(entry.get("symbol", ""))
        if symbol not in symbols:
            continue
        filters = entry.get("filters")
        if not isinstance(filters, list):
            raise InstrumentError(f"{symbol}: no filters in the exchange information")
        found[symbol] = InstrumentSpec(
            symbol=symbol,
            base_asset=str(entry["baseAsset"]),
            quote_asset=str(entry["quoteAsset"]),
            tick_size=_filter_value(filters, "PRICE_FILTER", "tickSize", symbol),
            lot_size=_filter_value(filters, "LOT_SIZE", "stepSize", symbol),
            status=str(entry.get("status", "")),
        )

    missing = sorted(set(symbols) - set(found))
    if missing:
        raise InstrumentError(f"Binance returned no exchange information for {missing}")
    return found


def fetch_exchange_info(
    symbols: list[str], get_text: Callable[[str], str] = fetch_text
) -> dict[str, InstrumentSpec]:
    """Download and parse the exchange information for these symbols."""
    if not symbols:
        raise InstrumentError("give at least one symbol")
    raw = get_text(exchange_info_url(symbols))
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InstrumentError(f"exchange information is not valid JSON ({exc})") from exc
    return parse_exchange_info(payload, symbols)


def first_data_date(symbol: str, interval: str = "1h", out_dir: Path = DEFAULT_OUT_DIR) -> date:
    """The day of the earliest bar we hold for this coin."""
    micros = first_open_time(symbol, interval, out_dir)
    if micros is None:
        raise BarBuildError(f"no {interval} bars for {symbol}; run build_bars.py first")
    return datetime.fromtimestamp(micros / 1_000_000, tz=UTC).date()


def build_specs(
    symbols: list[str],
    interval: str = "1h",
    out_dir: Path = DEFAULT_OUT_DIR,
    get_text: Callable[[str], str] = fetch_text,
) -> list[InstrumentSpec]:
    """Exchange information plus the first date we have data for, one entry per coin."""
    info = fetch_exchange_info(symbols, get_text)
    return [
        InstrumentSpec(
            **{
                **info[symbol].__dict__,
                "first_available_date": first_data_date(symbol, interval, out_dir),
            }
        )
        for symbol in symbols
    ]


UPSERT = text("""
INSERT INTO instruments
    (symbol, venue, base_asset, quote_asset, tick_size, lot_size, first_available_date, active)
VALUES
    (:symbol, :venue, :base_asset, :quote_asset, :tick_size, :lot_size, :first_available_date,
     :active)
ON CONFLICT (symbol) DO UPDATE SET
    venue = EXCLUDED.venue,
    base_asset = EXCLUDED.base_asset,
    quote_asset = EXCLUDED.quote_asset,
    tick_size = EXCLUDED.tick_size,
    lot_size = EXCLUDED.lot_size,
    first_available_date = EXCLUDED.first_available_date,
    active = EXCLUDED.active
""")


def seed_instruments(
    connection: Connection, specs: list[InstrumentSpec], venue: str = "binance_spot"
) -> int:
    """Write the coins into `instruments`; returns how many rows were written.

    Running this again with the same data changes nothing, so it is safe to repeat after
    every rebuild.
    """
    for spec in specs:
        if spec.first_available_date is None:
            raise InstrumentError(f"{spec.symbol}: first_available_date is not set")
        connection.execute(
            UPSERT,
            {
                "symbol": spec.symbol,
                "venue": venue,
                "base_asset": spec.base_asset,
                "quote_asset": spec.quote_asset,
                "tick_size": spec.tick_size,
                "lot_size": spec.lot_size,
                "first_available_date": spec.first_available_date,
                "active": spec.active,
            },
        )
    return len(specs)
