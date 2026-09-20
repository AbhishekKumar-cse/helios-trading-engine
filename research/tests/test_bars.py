"""Tests for building Parquet bars (step 051).

A fake data folder is built from the two committed fixture zips, so these run without the
real 240 MB dataset (and on CI).
"""

import shutil
from pathlib import Path

import pandas as pd
import pytest

from helios.data.bars import (
    BAR_COLUMNS,
    BarBuildError,
    build_bars,
    load_history,
    monthly_zips,
    read_bars,
    write_bars,
)
from helios.data.klines import normalise_klines, read_klines

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """A data folder holding BTCUSDT 1h for 2024-12 (ms) and 2025-01 (us)."""
    folder = tmp_path / "binance" / "spot" / "klines_1h"
    folder.mkdir(parents=True)
    for name in ("BTCUSDT-1h-2024-12.zip", "BTCUSDT-1h-2025-01.zip"):
        shutil.copy(FIXTURES / name, folder / name)
    return tmp_path


def test_monthly_zips_are_found_in_order(data_dir: Path) -> None:
    files = monthly_zips("BTCUSDT", "1h", data_dir)
    assert [f.name for f in files] == [
        "BTCUSDT-1h-2024-12.zip",
        "BTCUSDT-1h-2025-01.zip",
    ]


def test_history_joins_months_with_one_time_unit(data_dir: Path) -> None:
    frame = load_history("BTCUSDT", "1h", data_dir)
    assert len(frame) == 6  # 3 rows per fixture
    assert frame["open_time"].is_monotonic_increasing
    assert (frame["open_time"] > 10**14).all()  # everything in microseconds


def test_build_writes_one_parquet_per_year(data_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "processed"
    result = build_bars("BTCUSDT", "1h", data_dir, out)
    assert result.rows == 6
    assert result.months_read == 2
    assert len(result.files_written) == 2  # 2024 and 2025
    assert (
        out / "source=binance" / "interval=1h" / "symbol=BTCUSDT" / "year=2024" / "bars.parquet"
    ).is_file()
    assert (
        out / "source=binance" / "interval=1h" / "symbol=BTCUSDT" / "year=2025" / "bars.parquet"
    ).is_file()


def test_written_bars_round_trip(data_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "processed"
    build_bars("BTCUSDT", "1h", data_dir, out)
    back = read_bars("BTCUSDT", "1h", out)
    assert list(back.columns) == list(BAR_COLUMNS)  # 'ignore' is dropped
    assert len(back) == 6
    assert back["open_time"].dtype == "int64"
    original = normalise_klines(read_klines(FIXTURES / "BTCUSDT-1h-2024-12.zip"))
    assert back["close"].iloc[0] == original["close"].iloc[0]


def test_one_year_can_be_read(data_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "processed"
    build_bars("BTCUSDT", "1h", data_dir, out)
    assert len(read_bars("BTCUSDT", "1h", out, year=2025)) == 3


def test_clean_fixtures_report_nothing_wrong(data_dir: Path, tmp_path: Path) -> None:
    result = build_bars("BTCUSDT", "1h", data_dir, tmp_path / "processed")
    assert result.bad_rows.empty
    assert result.off_grid.empty
    assert result.duplicates_dropped == 0


def test_duplicate_months_are_dropped_once(data_dir: Path, tmp_path: Path) -> None:
    """Copying a month under a second name must not double the bars."""
    folder = data_dir / "binance" / "spot" / "klines_1h"
    shutil.copy(folder / "BTCUSDT-1h-2024-12.zip", folder / "BTCUSDT-1h-2024-11.zip")
    result = build_bars("BTCUSDT", "1h", data_dir, tmp_path / "processed")
    assert result.duplicates_dropped == 3
    assert result.rows == 6


def test_gaps_are_reported_not_filled(data_dir: Path, tmp_path: Path) -> None:
    result = build_bars("BTCUSDT", "1h", data_dir, tmp_path / "processed")
    # the two fixtures are a month apart, so the hours in between count as missing
    assert result.missing_bars > 700
    assert result.rows == 6  # nothing was invented to fill them


def test_dry_run_writes_nothing(data_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "processed"
    result = build_bars("BTCUSDT", "1h", data_dir, out, write=False)
    assert result.rows == 6
    assert result.files_written == []
    assert not out.exists()


def test_missing_symbol_is_rejected(data_dir: Path) -> None:
    with pytest.raises(BarBuildError, match="no 1h zips for ETHUSDT"):
        build_bars("ETHUSDT", "1h", data_dir, data_dir / "out")


def test_empty_frame_cannot_be_written(tmp_path: Path) -> None:
    with pytest.raises(BarBuildError, match="nothing to write"):
        write_bars(pd.DataFrame(), "BTCUSDT", "1h", tmp_path)


def test_reading_missing_bars_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(BarBuildError, match="no bars under"):
        read_bars("BTCUSDT", "1h", tmp_path)
