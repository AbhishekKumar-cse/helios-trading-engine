"""Tests for planning Binance kline downloads (step 039). No network access is used."""

from pathlib import Path

import pytest

from helios.data.binance import (
    BinanceDownloadError,
    KlineFile,
    Month,
    main,
    month_range,
    plan_klines,
    resolve_symbols,
)


def test_month_parse_and_str() -> None:
    assert Month.parse("2026-08") == Month(2026, 8)
    assert str(Month(2017, 8)) == "2017-08"


@pytest.mark.parametrize("bad", ["2026-13", "2026-00", "26-08", "2026/08", "2026-8"])
def test_bad_month_is_rejected(bad: str) -> None:
    with pytest.raises(BinanceDownloadError, match="YYYY-MM"):
        Month.parse(bad)


def test_month_range_crosses_year_end() -> None:
    months = month_range(Month(2025, 11), Month(2026, 2))
    assert [str(m) for m in months] == ["2025-11", "2025-12", "2026-01", "2026-02"]


def test_month_range_single_month() -> None:
    assert month_range(Month(2026, 8), Month(2026, 8)) == [Month(2026, 8)]


def test_month_range_rejects_reversed() -> None:
    with pytest.raises(BinanceDownloadError, match="after end"):
        month_range(Month(2026, 8), Month(2026, 7))


def test_url_and_path_match_existing_layout(tmp_path: Path) -> None:
    f = KlineFile("BTCUSDT", "1h", Month(2026, 8), tmp_path)
    assert f.url == (
        "https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1h/BTCUSDT-1h-2026-08.zip"
    )
    assert f.checksum_url == f.url + ".CHECKSUM"
    assert f.path == tmp_path / "binance" / "spot" / "klines_1h" / "BTCUSDT-1h-2026-08.zip"


def test_full_btc_hourly_history_is_109_months() -> None:
    files = plan_klines(["BTCUSDT"], "1h", Month(2017, 8), Month(2026, 8))
    assert len(files) == 109  # matches the 109 files already downloaded


def test_plan_orders_symbol_then_month() -> None:
    files = plan_klines(["ETHUSDT", "SOLUSDT"], "1m", Month(2026, 7), Month(2026, 8))
    assert [(f.symbol, str(f.month)) for f in files] == [
        ("ETHUSDT", "2026-07"),
        ("ETHUSDT", "2026-08"),
        ("SOLUSDT", "2026-07"),
        ("SOLUSDT", "2026-08"),
    ]


@pytest.mark.parametrize(
    ("symbols", "interval", "message"),
    [
        (["btcusdt"], "1h", "upper-case"),
        (["BTC-USDT"], "1h", "upper-case"),
        ([], "1h", "at least one symbol"),
        (["BTCUSDT"], "7m", "interval must be one of"),
    ],
)
def test_bad_requests_are_rejected(symbols: list[str], interval: str, message: str) -> None:
    with pytest.raises(BinanceDownloadError, match=message):
        plan_klines(symbols, interval, Month(2026, 8), Month(2026, 8))


def test_universe_expands_to_config_coins() -> None:
    assert resolve_symbols(["universe", "BTCUSDT"]) == [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "BNBUSDT",
        "XRPUSDT",
    ]


def test_dry_run_prints_plan(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    existing = KlineFile("BTCUSDT", "1h", Month(2026, 7), tmp_path).path
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"zip")
    code = main(
        ["--symbol", "BTCUSDT", "--interval", "1h", "--start", "2026-07", "--end", "2026-08",
         "--data-dir", str(tmp_path), "--dry-run"]
    )  # fmt: skip
    out = capsys.readouterr().out
    assert code == 0
    assert "exists " in out and "BTCUSDT-1h-2026-07.zip" in out
    assert "missing" in out and "BTCUSDT-1h-2026-08.zip" in out
    assert "2 files planned: 1 already on disk, 1 to download" in out


def test_without_dry_run_refuses_until_step_040(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        ["--symbol", "BTCUSDT", "--interval", "1h", "--start", "2026-08", "--end", "2026-08"]
    )
    assert code == 2
    assert "step 040" in capsys.readouterr().err


def test_bad_month_on_command_line(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        ["--symbol", "BTCUSDT", "--interval", "1h", "--start", "2026-8", "--end", "2026-08"]
    )
    assert code == 2
    assert "YYYY-MM" in capsys.readouterr().err
