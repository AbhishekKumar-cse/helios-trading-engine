"""Tests for loading bars with DuckDB (step 054).

A small Parquet store is built from the two committed fixture zips, so these run anywhere.
"""

import shutil
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from helios.data.bars import BAR_COLUMNS, BarBuildError, build_bars
from helios.data.klines import KlineFormatError
from helios.data.loader import available_symbols, load_bars, to_micros

FIXTURES = Path(__file__).parent / "fixtures"
DEC_FIRST = 1733011200000000  # 2024-12-01 00:00 UTC
JAN_FIRST = 1735689600000000  # 2025-01-01 00:00 UTC


@pytest.fixture
def store(tmp_path: Path) -> Path:
    """Parquet bars for two coins: 3 hourly bars in 2024-12 and 3 in 2025-01."""
    raw = tmp_path / "raw" / "binance" / "spot" / "klines_1h"
    raw.mkdir(parents=True)
    for symbol in ("BTCUSDT", "ETHUSDT"):
        for month in ("2024-12", "2025-01"):
            shutil.copy(FIXTURES / f"BTCUSDT-1h-{month}.zip", raw / f"{symbol}-1h-{month}.zip")
    out = tmp_path / "bars"
    for symbol in ("BTCUSDT", "ETHUSDT"):
        build_bars(symbol, "1h", tmp_path / "raw", out)
    return out


def test_loads_all_bars_with_symbol_column(store: Path) -> None:
    frame = load_bars(["BTCUSDT", "ETHUSDT"], "1h", out_dir=store)
    assert list(frame.columns) == ["symbol", *BAR_COLUMNS]
    assert len(frame) == 12  # 2 coins x 6 bars
    assert set(frame["symbol"]) == {"BTCUSDT", "ETHUSDT"}


def test_oldest_first(store: Path) -> None:
    frame = load_bars(["BTCUSDT", "ETHUSDT"], "1h", out_dir=store)
    assert frame["open_time"].is_monotonic_increasing


def test_one_symbol_as_a_string(store: Path) -> None:
    frame = load_bars("BTCUSDT", "1h", out_dir=store)
    assert set(frame["symbol"]) == {"BTCUSDT"}
    assert len(frame) == 6


def test_time_filter_keeps_only_the_range(store: Path) -> None:
    frame = load_bars("BTCUSDT", "1h", "2025-01-01", "2025-01-31", out_dir=store)
    assert len(frame) == 3
    assert frame["open_time"].min() == JAN_FIRST


def test_end_date_includes_the_whole_day(store: Path) -> None:
    """2024-12-01 as an end date must include that day's bars, not stop at midnight."""
    frame = load_bars("BTCUSDT", "1h", "2024-12-01", "2024-12-01", out_dir=store)
    assert len(frame) == 3


def test_start_only_and_end_only(store: Path) -> None:
    assert len(load_bars("BTCUSDT", "1h", start="2025-01-01", out_dir=store)) == 3
    assert len(load_bars("BTCUSDT", "1h", end="2024-12-31", out_dir=store)) == 3


def test_dates_and_datetimes_work(store: Path) -> None:
    by_date = load_bars("BTCUSDT", "1h", date(2025, 1, 1), date(2025, 1, 31), out_dir=store)
    by_datetime = load_bars(
        "BTCUSDT",
        "1h",
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 1, 31, 23, 59, tzinfo=UTC),
        out_dir=store,
    )
    assert len(by_date) == len(by_datetime) == 3


def test_range_outside_the_data_is_empty(store: Path) -> None:
    frame = load_bars("BTCUSDT", "1h", "2026-01-01", "2026-12-31", out_dir=store)
    assert frame.empty


def test_unknown_symbol_is_rejected(store: Path) -> None:
    with pytest.raises(BarBuildError, match="no bars found"):
        load_bars("DOGEUSDT", "1h", out_dir=store)


def test_one_known_symbol_among_unknown_still_loads(store: Path) -> None:
    frame = load_bars(["BTCUSDT", "DOGEUSDT"], "1h", out_dir=store)
    assert set(frame["symbol"]) == {"BTCUSDT"}


def test_reversed_range_is_rejected(store: Path) -> None:
    with pytest.raises(BarBuildError, match="is after end"):
        load_bars("BTCUSDT", "1h", "2025-06-01", "2025-01-01", out_dir=store)


def test_no_symbols_is_rejected(store: Path) -> None:
    with pytest.raises(BarBuildError, match="at least one symbol"):
        load_bars([], "1h", out_dir=store)


def test_unknown_interval_is_rejected(store: Path) -> None:
    with pytest.raises(KlineFormatError, match="unknown interval"):
        load_bars("BTCUSDT", "7m", out_dir=store)


def test_missing_interval_folder_is_rejected(store: Path) -> None:
    with pytest.raises(BarBuildError, match="no bars for interval 1m"):
        load_bars("BTCUSDT", "1m", out_dir=store)


def test_available_symbols(store: Path) -> None:
    assert available_symbols("1h", store) == ["BTCUSDT", "ETHUSDT"]


def test_values_match_the_parquet(store: Path) -> None:
    frame = load_bars("BTCUSDT", "1h", out_dir=store)
    first = frame.iloc[0]
    assert first["open_time"] == DEC_FIRST
    assert first["open"] == pytest.approx(96407.99)
    assert pd.api.types.is_integer_dtype(frame["trades"])


def test_date_string_and_date_object_agree() -> None:
    """A day written as text must cover the same range as the date itself."""
    assert to_micros("2024-12-01", end=True) == to_micros(date(2024, 12, 1), end=True)
    assert to_micros("2024-12-01T09:30", end=True) == to_micros(
        datetime(2024, 12, 1, 9, 30, tzinfo=UTC)
    )


def test_to_micros_handles_every_input() -> None:
    assert to_micros(None) is None
    assert to_micros(DEC_FIRST) == DEC_FIRST
    assert to_micros("2024-12-01") == DEC_FIRST
    assert to_micros(date(2024, 12, 1)) == DEC_FIRST
    assert to_micros(date(2024, 12, 1), end=True) == DEC_FIRST + 86_400_000_000 - 1
    assert to_micros(datetime(2024, 12, 1, tzinfo=UTC)) == DEC_FIRST


def test_numpy_integer_timestamp_works(store: Path) -> None:
    """A timestamp taken straight from a column is a numpy integer, not a Python int."""
    frame = load_bars("BTCUSDT", "1h", out_dir=store)
    first = frame["open_time"].min()
    assert isinstance(first, np.integer)
    assert to_micros(first) == DEC_FIRST
    assert len(load_bars("BTCUSDT", "1h", first, frame["open_time"].max(), out_dir=store)) == 6


def test_booleans_are_rejected() -> None:
    with pytest.raises(BarBuildError, match="cannot be True or False"):
        to_micros(True)


def test_naive_datetime_is_treated_as_utc() -> None:
    assert to_micros(datetime(2024, 12, 1)) == DEC_FIRST  # noqa: DTZ001 - the point of the test
