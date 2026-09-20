"""Tests for the point-in-time universe (step 060).

Each test writes its own coins with known dates inside a transaction that is rolled back, so
the tests do not depend on what the table already holds. One extra test checks the real
seeded coins when they are present.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Connection, text

from helios.data.instruments import InstrumentSpec, seed_instruments
from helios.data.universe import (
    UniverseError,
    first_full_universe_date,
    is_tradable_on,
    listing_dates,
    universe_on,
)

VENUE = "test_venue"  # keeps these coins out of the real binance_spot universe


def coin(symbol: str, first: date, status: str = "TRADING") -> InstrumentSpec:
    return InstrumentSpec(
        symbol=symbol,
        base_asset=symbol.removesuffix("USDT"),
        quote_asset="USDT",
        tick_size=Decimal("0.01"),
        lot_size=Decimal("0.001"),
        status=status,
        first_available_date=first,
    )


@pytest.fixture
def three_coins(connection: Connection) -> Connection:
    """An old coin, a middle one, and one that only appears in 2020 (like SOL)."""
    seed_instruments(
        connection,
        [
            coin("TESTOLDUSDT", date(2017, 8, 17)),
            coin("TESTMIDUSDT", date(2018, 5, 4)),
            coin("TESTNEWUSDT", date(2020, 8, 11)),
        ],
        venue=VENUE,
    )
    return connection


def test_a_coin_listed_later_is_excluded(three_coins: Connection) -> None:
    """The point of this step: no trading a coin that did not exist yet."""
    in_2019 = universe_on(three_coins, date(2019, 6, 1), VENUE)
    assert "TESTNEWUSDT" not in in_2019
    assert in_2019 == ["TESTMIDUSDT", "TESTOLDUSDT"]


def test_everything_is_there_once_all_have_started(three_coins: Connection) -> None:
    assert universe_on(three_coins, date(2021, 1, 1), VENUE) == [
        "TESTMIDUSDT",
        "TESTNEWUSDT",
        "TESTOLDUSDT",
    ]


def test_the_first_day_counts(three_coins: Connection) -> None:
    """A coin is in the universe on its own first day: a full day of bars exists."""
    assert "TESTNEWUSDT" in universe_on(three_coins, date(2020, 8, 11), VENUE)


def test_the_day_before_does_not_count(three_coins: Connection) -> None:
    assert "TESTNEWUSDT" not in universe_on(three_coins, date(2020, 8, 10), VENUE)


def test_before_everything_the_universe_is_empty(three_coins: Connection) -> None:
    assert universe_on(three_coins, date(2016, 1, 1), VENUE) == []


def test_an_inactive_coin_is_left_out(connection: Connection) -> None:
    seed_instruments(
        connection,
        [coin("TESTLIVEUSDT", date(2018, 1, 1)), coin("TESTDEADUSDT", date(2018, 1, 1), "BREAK")],
        venue=VENUE,
    )
    assert universe_on(connection, date(2024, 1, 1), VENUE) == ["TESTLIVEUSDT"]
    with_dead = universe_on(connection, date(2024, 1, 1), VENUE, include_inactive=True)
    assert with_dead == ["TESTDEADUSDT", "TESTLIVEUSDT"]


def test_one_coin_can_be_checked_directly(three_coins: Connection) -> None:
    assert is_tradable_on(three_coins, "TESTNEWUSDT", date(2021, 1, 1)) is True
    assert is_tradable_on(three_coins, "TESTNEWUSDT", date(2019, 1, 1)) is False


def test_an_unknown_coin_is_refused(three_coins: Connection) -> None:
    with pytest.raises(UniverseError, match="not in the instruments table"):
        is_tradable_on(three_coins, "NOSUCHUSDT", date(2021, 1, 1))


def test_listing_dates_are_returned(three_coins: Connection) -> None:
    dates = listing_dates(three_coins, VENUE)
    assert dates["TESTOLDUSDT"] == date(2017, 8, 17)
    assert dates["TESTNEWUSDT"] == date(2020, 8, 11)


def test_an_empty_venue_is_refused(connection: Connection) -> None:
    with pytest.raises(UniverseError, match="run scripts/seed_instruments.py"):
        listing_dates(connection, "venue_that_does_not_exist")


def test_first_full_universe_date_is_the_newest_listing(three_coins: Connection) -> None:
    assert first_full_universe_date(three_coins, VENUE) == date(2020, 8, 11)


def test_the_universe_only_grows(three_coins: Connection) -> None:
    """Coins are never removed as time moves forward, so results stay comparable."""
    days = [date(2017, 1, 1), date(2018, 1, 1), date(2019, 1, 1), date(2021, 1, 1)]
    sizes = [len(universe_on(three_coins, day, VENUE)) for day in days]
    assert sizes == sorted(sizes)
    assert sizes == [0, 1, 2, 3]


# ---------------------------------------------------------------- the real coins


def test_the_real_universe_excludes_sol_in_2019(connection: Connection) -> None:
    """The check the step asks for, against the coins seeded from real data."""
    try:
        real = listing_dates(connection)
    except UniverseError:
        pytest.skip("instruments not seeded yet (run scripts/seed_instruments.py)")

    assert real["SOLUSDT"] == date(2020, 8, 11)
    in_2019 = universe_on(connection, date(2019, 6, 1))
    assert "SOLUSDT" not in in_2019
    assert {"BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT"} <= set(in_2019)
    assert set(universe_on(connection, date(2026, 1, 1))) == set(real)


def test_the_real_universe_on_the_hourly_train_start(connection: Connection) -> None:
    """ADR-004 starts hourly TRAIN on 2018-01-01: SOL and XRP are not there yet."""
    try:
        listing_dates(connection)
    except UniverseError:
        pytest.skip("instruments not seeded yet")
    assert universe_on(connection, date(2018, 1, 1)) == ["BNBUSDT", "BTCUSDT", "ETHUSDT"]


def test_a_committed_row_is_not_left_behind(connection: Connection) -> None:
    """Sanity: the test coins above never escape their transaction."""
    leaked = connection.execute(
        text("SELECT count(*) FROM instruments WHERE venue = :venue"), {"venue": VENUE}
    ).scalar_one()
    assert leaked == 0
