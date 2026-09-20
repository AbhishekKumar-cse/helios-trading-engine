"""Tests for reading and time-normalising Binance kline zips (steps 045-048).

The fixtures are 3 real rows each from two real monthly files, small enough to commit:
2024-12 (timestamps in milliseconds) and 2025-01 (microseconds).
"""

import zipfile
from pathlib import Path

import pandas as pd
import pytest

from helios.data.klines import (
    COLUMNS,
    KlineFormatError,
    find_duplicates,
    find_gaps,
    find_off_grid,
    interval_us,
    normalise_klines,
    normalise_ts,
    read_klines,
    to_utc,
    validate_bars,
)

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


# ---------------------------------------------------------------- one time unit (step 046)


def test_milliseconds_row_from_2024_becomes_microseconds() -> None:
    frame = normalise_klines(read_klines(MS_FIXTURE))
    assert frame["open_time"].iloc[0] == 1733011200000000
    assert str(to_utc(frame["open_time"]).iloc[0]) == "2024-12-01 00:00:00+00:00"


def test_microseconds_row_from_2025_is_left_alone() -> None:
    raw = read_klines(US_FIXTURE)
    frame = normalise_klines(raw)
    assert frame["open_time"].iloc[0] == raw["open_time"].iloc[0] == 1735689600000000
    assert str(to_utc(frame["open_time"]).iloc[0]) == "2025-01-01 00:00:00+00:00"


def test_both_months_line_up_on_one_timeline() -> None:
    """The real point of this step: December 2024 must come before January 2025."""
    december = normalise_klines(read_klines(MS_FIXTURE))["open_time"].iloc[0]
    january = normalise_klines(read_klines(US_FIXTURE))["open_time"].iloc[0]
    assert december < january
    gap_days = (january - december) / 1e6 / 86400
    assert gap_days == pytest.approx(31.0)


def test_mixed_units_in_one_column() -> None:
    mixed = pd.Series([1733011200000, 1735689600000000], dtype="int64")
    assert normalise_ts(mixed).tolist() == [1733011200000000, 1735689600000000]


def test_result_is_int64_and_unchanged_columns() -> None:
    raw = read_klines(MS_FIXTURE)
    frame = normalise_klines(raw)
    assert frame["open_time"].dtype == "int64"
    assert frame["close_time"].dtype == "int64"
    assert list(frame.columns) == list(raw.columns)
    assert frame["close"].equals(raw["close"])  # prices untouched
    assert raw["open_time"].iloc[0] == 1733011200000  # original frame not modified


def test_close_time_is_converted_too() -> None:
    """A candle ends just before the next one starts, with the precision its file was written
    in: millisecond files stop 1 ms early, microsecond files 1 us early."""
    one_hour_us = 3600 * 10**6
    from_ms = normalise_klines(read_klines(MS_FIXTURE))
    assert from_ms["close_time"].iloc[0] == from_ms["open_time"].iloc[0] + one_hour_us - 1000
    from_us = normalise_klines(read_klines(US_FIXTURE))
    assert from_us["close_time"].iloc[0] == from_us["open_time"].iloc[0] + one_hour_us - 1


def test_seconds_would_be_out_of_range() -> None:
    """A file in seconds (not a unit Binance uses) must fail loudly, not convert silently."""
    with pytest.raises(KlineFormatError, match="outside 2009-2100"):
        normalise_ts(pd.Series([1733011200], dtype="int64"))


def test_zero_and_negative_are_rejected() -> None:
    for bad in ([0], [-1733011200000]):
        with pytest.raises(KlineFormatError, match="outside 2009-2100"):
            normalise_ts(pd.Series(bad, dtype="int64"))


def test_non_integer_column_is_rejected() -> None:
    with pytest.raises(KlineFormatError, match="whole numbers"):
        normalise_ts(pd.Series([1733011200000.5]))


def test_empty_column_is_rejected() -> None:
    with pytest.raises(KlineFormatError, match="no timestamps"):
        normalise_ts(pd.Series([], dtype="int64"))


def test_missing_column_is_rejected() -> None:
    with pytest.raises(KlineFormatError, match="'open_time' is missing"):
        normalise_klines(pd.DataFrame({"close_time": [1733011200000]}))


# ---------------------------------------------------------------- checking rows (step 047)


def good_frame() -> pd.DataFrame:
    return normalise_klines(read_klines(MS_FIXTURE))


def test_real_fixture_rows_are_all_valid() -> None:
    bad = validate_bars(good_frame())
    assert bad.empty
    assert "problems" in bad.columns  # same shape even when nothing is wrong


@pytest.mark.parametrize(
    ("column", "value", "expected"),
    [
        ("open", 0.0, "price not above zero"),
        ("close", -1.0, "price not above zero"),
        ("high", 1.0, "high below open or close"),
        ("low", 10**9, "low above open or close"),
        ("volume", -0.5, "negative volume"),
        ("quote_volume", -1.0, "negative volume"),
        ("trades", -3, "negative trade count"),
        ("taker_buy_base", 10**9, "taker volume above total volume"),
    ],
)
def test_one_broken_value_is_reported(column: str, value: float, expected: str) -> None:
    frame = good_frame()
    frame.loc[1, column] = value
    bad = validate_bars(frame)
    assert len(bad) == 1
    assert bad.index.tolist() == [1]
    assert expected in bad["problems"].iloc[0]


def test_missing_value_is_reported() -> None:
    frame = good_frame()
    frame.loc[0, "close"] = float("nan")
    bad = validate_bars(frame)
    assert bad["problems"].iloc[0].startswith("missing value")


def test_high_below_low_is_reported() -> None:
    frame = good_frame()
    frame.loc[2, ["open", "close", "high", "low"]] = [100.0, 100.0, 90.0, 110.0]
    problems = validate_bars(frame)["problems"].iloc[0]
    assert "high below low" in problems
    assert "high below open or close" in problems  # several rules can break at once


def test_bad_rows_are_returned_untouched() -> None:
    frame = good_frame()
    frame.loc[1, "open"] = -5.0
    bad = validate_bars(frame)
    assert bad["open"].iloc[0] == -5.0  # reported as-is, never repaired
    assert len(frame) == 3  # nothing dropped from the input either


def test_all_rows_can_be_bad() -> None:
    frame = good_frame()
    frame["volume"] = -1.0
    assert len(validate_bars(frame)) == 3


def test_missing_columns_are_rejected() -> None:
    with pytest.raises(KlineFormatError, match="columns missing for validation"):
        validate_bars(pd.DataFrame({"open": [1.0]}))


# ---------------------------------------------------------------- gaps and duplicates (048)


def hourly_frame(hours: int = 6) -> pd.DataFrame:
    """A clean hourly frame starting 2025-01-01 00:00 UTC."""
    step = interval_us("1h")
    start = 1735689600000000
    return pd.DataFrame({"open_time": [start + i * step for i in range(hours)], "close": 1.0})


def test_clean_hours_have_no_gaps() -> None:
    assert find_gaps(hourly_frame(), "1h").empty


def test_one_deleted_row_appears_as_a_gap() -> None:
    frame = hourly_frame().drop(index=2).reset_index(drop=True)
    gaps = find_gaps(frame, "1h")
    assert len(gaps) == 1
    assert gaps["missing"].iloc[0] == 1
    assert gaps["gap_start"].iloc[0] == gaps["gap_end"].iloc[0]
    assert str(gaps["gap_start_utc"].iloc[0]) == "2025-01-01 02:00:00+00:00"


def test_several_missing_hours_are_one_run() -> None:
    frame = hourly_frame(10).drop(index=[3, 4, 5]).reset_index(drop=True)
    gaps = find_gaps(frame, "1h")
    assert len(gaps) == 1
    assert gaps["missing"].iloc[0] == 3
    assert str(gaps["gap_start_utc"].iloc[0]) == "2025-01-01 03:00:00+00:00"
    assert str(gaps["gap_end_utc"].iloc[0]) == "2025-01-01 05:00:00+00:00"


def test_two_separate_gaps() -> None:
    frame = hourly_frame(10).drop(index=[2, 6, 7]).reset_index(drop=True)
    gaps = find_gaps(frame, "1h")
    assert gaps["missing"].tolist() == [1, 2]


def test_gaps_never_change_the_data() -> None:
    frame = hourly_frame().drop(index=2).reset_index(drop=True)
    before = frame.copy()
    find_gaps(frame, "1h")
    assert frame.equals(before)  # nothing filled in


def test_minute_interval() -> None:
    step = interval_us("1m")
    start = 1735689600000000
    frame = pd.DataFrame({"open_time": [start, start + step, start + 4 * step]})
    gaps = find_gaps(frame, "1m")
    assert gaps["missing"].tolist() == [2]


def test_unsorted_rows_are_still_understood() -> None:
    frame = hourly_frame().drop(index=2).sample(frac=1, random_state=0)
    assert find_gaps(frame, "1h")["missing"].tolist() == [1]


def test_duplicates_are_found_and_not_counted_as_gaps() -> None:
    frame = pd.concat([hourly_frame(), hourly_frame().iloc[[1]]], ignore_index=True)
    assert len(find_duplicates(frame)) == 2  # both copies are returned
    assert find_gaps(frame, "1h").empty


def test_no_duplicates_in_clean_data() -> None:
    assert find_duplicates(hourly_frame()).empty


def test_off_grid_timestamps_are_found() -> None:
    frame = hourly_frame()
    frame.loc[1, "open_time"] += 30 * 10**6  # half a minute late
    off = find_off_grid(frame, "1h")
    assert len(off) == 1
    with pytest.raises(KlineFormatError, match="not on the 1h grid"):
        find_gaps(frame, "1h")


def test_unknown_interval_is_rejected() -> None:
    with pytest.raises(KlineFormatError, match="unknown interval"):
        find_gaps(hourly_frame(), "7m")


def test_empty_frame_is_rejected() -> None:
    with pytest.raises(KlineFormatError, match="no rows"):
        find_gaps(pd.DataFrame({"open_time": pd.Series([], dtype="int64")}), "1h")


def test_real_fixture_month_has_no_gaps() -> None:
    frame = normalise_klines(read_klines(MS_FIXTURE))
    assert find_gaps(frame, "1h").empty
    assert find_duplicates(frame).empty
