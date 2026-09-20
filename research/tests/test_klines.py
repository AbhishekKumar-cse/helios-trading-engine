"""Tests for reading Binance kline zips (step 045).

The fixtures are 3 real rows each from two real monthly files, small enough to commit:
2024-12 (timestamps in milliseconds) and 2025-01 (microseconds).
"""

import zipfile
from pathlib import Path

import pandas as pd
import pytest

from helios.data.klines import COLUMNS, KlineFormatError, read_klines

FIXTURES = Path(__file__).parent / "fixtures"
MS_FIXTURE = FIXTURES / "BTCUSDT-1h-2024-12.zip"
US_FIXTURE = FIXTURES / "BTCUSDT-1h-2025-01.zip"


def test_reads_twelve_named_columns() -> None:
    frame = read_klines(MS_FIXTURE)
    assert list(frame.columns) == list(COLUMNS)
    assert len(frame) == 3


def test_values_match_the_file() -> None:
    frame = read_klines(MS_FIXTURE)
    first = frame.iloc[0]
    assert first["open_time"] == 1733011200000  # 2024-12-01 00:00 UTC, in milliseconds
    assert first["open"] == pytest.approx(96407.99)
    assert first["high"] == pytest.approx(96672.49)
    assert first["low"] == pytest.approx(96260.00)
    assert first["close"] == pytest.approx(96340.60)
    assert first["trades"] == 154693


def test_dtypes_are_numeric() -> None:
    frame = read_klines(MS_FIXTURE)
    assert frame["open_time"].dtype == "int64"
    assert frame["close_time"].dtype == "int64"
    assert frame["trades"].dtype == "int64"
    for column in ("open", "high", "low", "close", "volume", "quote_volume"):
        assert frame[column].dtype == "float64"


def test_microsecond_file_reads_too() -> None:
    """Step 046 will unify the units; reading must already cope with both."""
    ms = read_klines(MS_FIXTURE)
    us = read_klines(US_FIXTURE)
    assert ms["open_time"].iloc[0] < 10**14  # milliseconds
    assert us["open_time"].iloc[0] > 10**14  # microseconds
    assert list(us.columns) == list(COLUMNS)


def test_path_may_be_a_string() -> None:
    assert len(read_klines(str(MS_FIXTURE))) == 3


def write_zip(path: Path, csv_name: str, text: str) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(csv_name, text)
    return path


def test_missing_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(KlineFormatError, match="file not found"):
        read_klines(tmp_path / "nope.zip")


def test_not_a_zip_is_rejected(tmp_path: Path) -> None:
    broken = tmp_path / "broken.zip"
    broken.write_bytes(b"this is not a zip")
    with pytest.raises(KlineFormatError, match="not a valid zip"):
        read_klines(broken)


def test_zip_without_exactly_one_csv_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "two.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("a.csv", "1,2\n")
        archive.writestr("b.csv", "3,4\n")
    with pytest.raises(KlineFormatError, match="expected 1 CSV"):
        read_klines(path)


def test_empty_csv_is_rejected(tmp_path: Path) -> None:
    write_zip(tmp_path / "empty.zip", "empty.csv", "")
    with pytest.raises(KlineFormatError, match="unexpected CSV content|contains no rows"):
        read_klines(tmp_path / "empty.zip")


def test_wrong_column_count_is_rejected(tmp_path: Path) -> None:
    write_zip(tmp_path / "short.zip", "short.csv", "1,2,3\n")
    with pytest.raises(KlineFormatError, match="unexpected CSV content"):
        read_klines(tmp_path / "short.zip")


def test_text_instead_of_numbers_is_rejected(tmp_path: Path) -> None:
    header = ",".join(COLUMNS) + "\n"
    write_zip(tmp_path / "header.zip", "header.csv", header + "1," * 11 + "1\n")
    with pytest.raises(KlineFormatError, match="unexpected CSV content"):
        read_klines(tmp_path / "header.zip")


@pytest.mark.parametrize("fixture", [MS_FIXTURE, US_FIXTURE])
def test_close_time_is_after_open_time(fixture: Path) -> None:
    frame = read_klines(fixture)
    assert (frame["close_time"] > frame["open_time"]).all()
    assert isinstance(frame, pd.DataFrame)
