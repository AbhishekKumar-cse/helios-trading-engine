"""Tests for seeding the instruments table (step 058).

The database tests use fake symbols (TESTAUSDT and friends) so they never collide with
the real coins this very step seeds.

No network is used: Binance's answer is replaced by a small fixed example. The database
tests run inside a transaction that is rolled back, and skip when no database is reachable.
"""

import json
import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Connection, text

from helios.data.bars import BarBuildError, build_bars
from helios.data.instruments import (
    InstrumentError,
    InstrumentSpec,
    build_specs,
    exchange_info_url,
    fetch_exchange_info,
    first_data_date,
    parse_exchange_info,
    seed_instruments,
)
from helios.data.loader import first_open_time

FIXTURES = Path(__file__).parent / "fixtures"
DEC_FIRST = date(2024, 12, 1)


def binance_answer(symbols: tuple[str, ...] = ("BTCUSDT",), status: str = "TRADING") -> str:
    """The shape Binance really returns, trimmed to what we read."""
    return json.dumps(
        {
            "symbols": [
                {
                    "symbol": symbol,
                    "status": status,
                    "baseAsset": symbol.removesuffix("USDT"),
                    "quoteAsset": "USDT",
                    "filters": [
                        {"filterType": "PRICE_FILTER", "minPrice": "0.01", "tickSize": "0.01"},
                        {"filterType": "LOT_SIZE", "minQty": "0.00001", "stepSize": "0.00001"},
                    ],
                }
                for symbol in symbols
            ]
        }
    )


@pytest.fixture
def store(tmp_path: Path) -> Path:
    """A tiny Parquet store holding BTCUSDT hourly bars for 2024-12 and 2025-01."""
    raw = tmp_path / "raw" / "binance" / "spot" / "klines_1h"
    raw.mkdir(parents=True)
    for month in ("2024-12", "2025-01"):
        shutil.copy(FIXTURES / f"BTCUSDT-1h-{month}.zip", raw / f"BTCUSDT-1h-{month}.zip")
    out = tmp_path / "bars"
    build_bars("BTCUSDT", "1h", tmp_path / "raw", out)
    return out


# ---------------------------------------------------------------- reading Binance's answer


def test_url_carries_the_symbols_as_json() -> None:
    url = exchange_info_url(["BTCUSDT", "ETHUSDT"])
    assert url.startswith("https://api.binance.com/api/v3/exchangeInfo?symbols=")
    assert "BTCUSDT" in url and "ETHUSDT" in url


def test_tick_and_lot_sizes_are_exact_decimals() -> None:
    specs = fetch_exchange_info(["BTCUSDT"], lambda url: binance_answer())
    spec = specs["BTCUSDT"]
    assert spec.tick_size == Decimal("0.01")
    assert spec.lot_size == Decimal("0.00001")
    assert isinstance(spec.tick_size, Decimal)  # never a float
    assert (spec.base_asset, spec.quote_asset) == ("BTC", "USDT")
    assert spec.active is True


def test_a_pair_that_is_not_trading_is_marked_inactive() -> None:
    specs = fetch_exchange_info(["BTCUSDT"], lambda url: binance_answer(status="BREAK"))
    assert specs["BTCUSDT"].active is False


def test_a_missing_symbol_is_an_error() -> None:
    with pytest.raises(InstrumentError, match="no exchange information for"):
        fetch_exchange_info(["BTCUSDT", "DOGEUSDT"], lambda url: binance_answer())


def test_a_missing_price_filter_is_an_error() -> None:
    payload = json.loads(binance_answer())
    payload["symbols"][0]["filters"] = [{"filterType": "LOT_SIZE", "minQty": "1", "stepSize": "1"}]
    with pytest.raises(InstrumentError, match="no PRICE_FILTER"):
        parse_exchange_info(payload, ["BTCUSDT"])


def test_broken_json_is_an_error() -> None:
    with pytest.raises(InstrumentError, match="not valid JSON"):
        fetch_exchange_info(["BTCUSDT"], lambda url: "{not json")


def test_no_symbols_is_an_error() -> None:
    with pytest.raises(InstrumentError, match="at least one symbol"):
        fetch_exchange_info([], lambda url: binance_answer())


# ---------------------------------------------------------------- the first date we hold


def test_first_date_comes_from_the_bars(store: Path) -> None:
    assert first_data_date("BTCUSDT", "1h", store) == DEC_FIRST


def test_first_open_time_returns_none_without_bars(tmp_path: Path) -> None:
    assert first_open_time("BTCUSDT", "1h", tmp_path) is None


def test_a_coin_without_bars_is_refused(store: Path) -> None:
    with pytest.raises(BarBuildError, match="run build_bars.py first"):
        first_data_date("ETHUSDT", "1h", store)


def test_build_specs_joins_both_sources(store: Path) -> None:
    specs = build_specs(["BTCUSDT"], "1h", store, lambda url: binance_answer())
    assert len(specs) == 1
    assert specs[0].tick_size == Decimal("0.01")  # from Binance
    assert specs[0].first_available_date == DEC_FIRST  # from our own bars


# ---------------------------------------------------------------- writing to the database


def spec(symbol: str = "TESTAUSDT", tick: str = "0.01") -> InstrumentSpec:
    return InstrumentSpec(
        symbol=symbol,
        base_asset=symbol.removesuffix("USDT"),
        quote_asset="USDT",
        tick_size=Decimal(tick),
        lot_size=Decimal("0.00001"),
        status="TRADING",
        first_available_date=DEC_FIRST,
    )


def count(connection: Connection) -> int:
    return connection.execute(text("SELECT count(*) FROM instruments")).scalar_one()


def test_rows_are_written(connection: Connection) -> None:
    before = count(connection)
    written = seed_instruments(connection, [spec("TESTAUSDT"), spec("TESTBUSDT")])
    assert written == 2
    assert count(connection) == before + 2
    row = connection.execute(
        text(
            "SELECT tick_size, first_available_date, active FROM instruments "
            "WHERE symbol = 'TESTAUSDT'"
        )
    ).one()
    assert row.tick_size == Decimal("0.01")
    assert row.first_available_date == DEC_FIRST
    assert row.active is True


def test_running_twice_does_not_duplicate(connection: Connection) -> None:
    seed_instruments(connection, [spec()])
    after_first = count(connection)
    seed_instruments(connection, [spec()])
    assert count(connection) == after_first


def test_a_changed_tick_size_updates_the_row(connection: Connection) -> None:
    seed_instruments(connection, [spec(tick="0.01")])
    seed_instruments(connection, [spec(tick="0.05")])
    tick = connection.execute(
        text("SELECT tick_size FROM instruments WHERE symbol = 'TESTAUSDT'")
    ).scalar_one()
    assert tick == Decimal("0.05")


def test_a_missing_first_date_is_refused(connection: Connection) -> None:
    without_date = InstrumentSpec(
        symbol="TESTEUSDT",
        base_asset="XRP",
        quote_asset="USDT",
        tick_size=Decimal("0.0001"),
        lot_size=Decimal("0.1"),
        status="TRADING",
    )
    with pytest.raises(InstrumentError, match="first_available_date is not set"):
        seed_instruments(connection, [without_date])
