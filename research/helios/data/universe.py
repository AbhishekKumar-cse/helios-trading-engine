"""Which coins may be traded on a given day (step 060).

A backtest that runs over 2019 must not be allowed to trade SOLUSDT, because Binance had no
such pair until August 2020. Including it would be **survivorship-style leakage**: the
backtest would quietly use knowledge that only exists today (which coins turned out to
matter) and its results would be impossible to achieve in real time.

The single source of truth is the `instruments` table (`first_available_date`, seeded in
step 058 from the earliest bar actually on disk). Research code asks this module rather than
hard-coding a coin list.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Connection, text
from sqlalchemy.engine import ScalarResult


class UniverseError(Exception):
    """Raised when the universe cannot be determined."""


LISTING_DATES = text("""
SELECT symbol, first_available_date, active
FROM instruments
-- the cast tells PostgreSQL the type: a parameter compared only to NULL is ambiguous
WHERE (CAST(:venue AS text) IS NULL OR venue = CAST(:venue AS text))
ORDER BY symbol
""")


def listing_dates(connection: Connection, venue: str | None = "binance_spot") -> dict[str, date]:
    """Every known coin and the first day we have data for it."""
    rows = connection.execute(LISTING_DATES, {"venue": venue}).all()
    if not rows:
        raise UniverseError("the instruments table is empty; run scripts/seed_instruments.py first")
    return {row.symbol: row.first_available_date for row in rows}


def universe_on(
    connection: Connection,
    on: date,
    venue: str | None = "binance_spot",
    *,
    include_inactive: bool = False,
) -> list[str]:
    """Coins whose data starts on or before `on`, in alphabetical order.

    The comparison is inclusive: a coin is in the universe on its own first day, because a
    full day of bars exists for it. Coins marked inactive are left out unless asked for,
    since a pair that no longer trades cannot be traded today.
    """
    rows: ScalarResult[str] = connection.execute(
        text("""
        SELECT symbol
        FROM instruments
        WHERE first_available_date <= :on
          AND (CAST(:venue AS text) IS NULL OR venue = CAST(:venue AS text))
          AND (CAST(:include_inactive AS boolean) OR active)
        ORDER BY symbol
        """),
        {"on": on, "venue": venue, "include_inactive": include_inactive},
    ).scalars()
    return list(rows)


def is_tradable_on(connection: Connection, symbol: str, on: date) -> bool:
    """Whether one coin may be traded on one day."""
    first = connection.execute(
        text("SELECT first_available_date FROM instruments WHERE symbol = :symbol"),
        {"symbol": symbol},
    ).scalar_one_or_none()
    if first is None:
        raise UniverseError(f"{symbol} is not in the instruments table")
    return bool(first <= on)


def first_full_universe_date(connection: Connection, venue: str | None = "binance_spot") -> date:
    """The first day on which every known coin has data.

    Useful when a study needs the same set of coins throughout: before this day the universe
    is still growing, which changes the meaning of a portfolio-level result.
    """
    return max(listing_dates(connection, venue).values())
