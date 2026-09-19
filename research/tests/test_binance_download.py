"""Tests for Binance kline downloads (steps 039-041). No real network access is used."""

import hashlib
import io
import urllib.error
from email.message import Message
from pathlib import Path

import pytest

from helios.data import binance
from helios.data.binance import (
    BinanceDownloadError,
    ChecksumMismatchError,
    DownloadStatus,
    KlineFile,
    Month,
    download_file,
    fetch_to_file,
    main,
    month_range,
    parse_checksum,
    plan_klines,
    resolve_symbols,
    run_downloads,
    sha256_file,
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


def test_bad_month_on_command_line(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        ["--symbol", "BTCUSDT", "--interval", "1h", "--start", "2026-8", "--end", "2026-08"]
    )
    assert code == 2
    assert "YYYY-MM" in capsys.readouterr().err


# ---------------------------------------------------------------- downloading (040-041)

PAYLOAD = b"zip-bytes"
GOOD_SHA = hashlib.sha256(PAYLOAD).hexdigest()


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://x", code, "error", Message(), io.BytesIO())


def kline(tmp_path: Path) -> KlineFile:
    return KlineFile("BTCUSDT", "1h", Month(2026, 8), tmp_path)


class FakeFetch:
    """Stands in for the network: raises the queued errors in order, then writes `payloads`
    in turn (the last one repeats)."""

    def __init__(self, *errors: Exception, payloads: tuple[bytes, ...] = (PAYLOAD,)) -> None:
        self.errors = list(errors)
        self.payloads = list(payloads)
        self.calls = 0

    def __call__(self, url: str, dest: Path) -> int:
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        data = self.payloads.pop(0) if len(self.payloads) > 1 else self.payloads[0]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return len(data)


class FakeText:
    """Serves the .CHECKSUM text (or raises the given error)."""

    def __init__(self, sha: str = GOOD_SHA, error: Exception | None = None) -> None:
        self.sha, self.error, self.calls = sha, error, 0

    def __call__(self, url: str) -> str:
        self.calls += 1
        if self.error:
            raise self.error
        return f"{self.sha}  {url.rsplit('/', 1)[1].removesuffix('.CHECKSUM')}"


def no_sleep(seconds: float) -> None:
    pass


def test_download_success_verifies_and_keeps_checksum(tmp_path: Path) -> None:
    f = kline(tmp_path)
    status, message = download_file(f, fetch=FakeFetch(), get_text=FakeText(), sleep=no_sleep)
    assert status is DownloadStatus.DOWNLOADED
    assert "checksum OK" in message
    assert f.path.read_bytes() == PAYLOAD
    assert f.checksum_path.read_text().startswith(GOOD_SHA)


def test_verified_file_is_skipped_offline(tmp_path: Path) -> None:
    f = kline(tmp_path)
    f.path.parent.mkdir(parents=True)
    f.path.write_bytes(PAYLOAD)
    f.checksum_path.write_text(f"{GOOD_SHA}  {f.filename}")
    fetch, text = FakeFetch(), FakeText()
    status, message = download_file(f, fetch=fetch, get_text=text, sleep=no_sleep)
    assert status is DownloadStatus.SKIPPED
    assert "checksum OK" in message
    assert (fetch.calls, text.calls) == (0, 0)  # no network at all


def test_existing_file_without_local_checksum_is_verified(tmp_path: Path) -> None:
    f = kline(tmp_path)
    f.path.parent.mkdir(parents=True)
    f.path.write_bytes(PAYLOAD)
    fetch, text = FakeFetch(), FakeText()
    status, _ = download_file(f, fetch=fetch, get_text=text, sleep=no_sleep)
    assert status is DownloadStatus.SKIPPED
    assert (fetch.calls, text.calls) == (0, 1)
    assert f.checksum_path.is_file()


def test_damaged_file_on_disk_is_replaced(tmp_path: Path) -> None:
    f = kline(tmp_path)
    f.path.parent.mkdir(parents=True)
    f.path.write_bytes(b"corrupted")
    status, message = download_file(f, fetch=FakeFetch(), get_text=FakeText(), sleep=no_sleep)
    assert status is DownloadStatus.DOWNLOADED
    assert "replaced a damaged file" in message
    assert f.path.read_bytes() == PAYLOAD


def test_mismatch_after_download_is_retried(tmp_path: Path) -> None:
    f = kline(tmp_path)
    fetch = FakeFetch(payloads=(b"bad-bytes", PAYLOAD))
    waits: list[float] = []
    status, _ = download_file(f, fetch=fetch, get_text=FakeText(), sleep=waits.append)
    assert status is DownloadStatus.DOWNLOADED
    assert fetch.calls == 2
    assert waits == [2.0]


def test_persistent_mismatch_fails_and_leaves_no_file(tmp_path: Path) -> None:
    f = kline(tmp_path)
    fetch = FakeFetch(payloads=(b"always-bad",))
    status, message = download_file(f, retries=2, fetch=fetch, get_text=FakeText(), sleep=no_sleep)
    assert status is DownloadStatus.FAILED
    assert "ChecksumMismatchError" in message
    assert fetch.calls == 3
    assert not f.path.exists()


def test_checksum_404_means_month_not_found(tmp_path: Path) -> None:
    fetch = FakeFetch()
    status, message = download_file(
        kline(tmp_path), fetch=fetch, get_text=FakeText(error=http_error(404)), sleep=no_sleep
    )
    assert status is DownloadStatus.NOT_FOUND
    assert "404" in message
    assert fetch.calls == 0


def test_network_errors_are_retried_with_growing_waits(tmp_path: Path) -> None:
    waits: list[float] = []
    fetch = FakeFetch(urllib.error.URLError("reset"), TimeoutError(), http_error(503))
    status, _ = download_file(
        kline(tmp_path),
        retries=4,
        backoff_seconds=2.0,
        fetch=fetch,
        get_text=FakeText(),
        sleep=waits.append,
    )
    assert status is DownloadStatus.DOWNLOADED
    assert fetch.calls == 4
    assert waits == [2.0, 4.0, 8.0]


def test_gives_up_after_all_retries(tmp_path: Path) -> None:
    fetch = FakeFetch(*[urllib.error.URLError("down")] * 10)
    status, message = download_file(
        kline(tmp_path), retries=2, fetch=fetch, get_text=FakeText(), sleep=no_sleep
    )
    assert status is DownloadStatus.FAILED
    assert fetch.calls == 3
    assert "URLError" in message
    assert not kline(tmp_path).path.exists()


def test_client_error_other_than_404_is_not_retried(tmp_path: Path) -> None:
    fetch = FakeFetch(http_error(403))
    status, _ = download_file(kline(tmp_path), fetch=fetch, get_text=FakeText(), sleep=no_sleep)
    assert status is DownloadStatus.FAILED
    assert fetch.calls == 1


def test_parse_checksum() -> None:
    assert parse_checksum(f"{GOOD_SHA.upper()}  a.zip", "a.zip") == GOOD_SHA
    for bad in ("", f"{GOOD_SHA}  other.zip", "xyz  a.zip", f"{GOOD_SHA} a.zip extra"):
        with pytest.raises(ChecksumMismatchError):
            parse_checksum(bad, "a.zip")


def test_sha256_file_matches_hashlib(tmp_path: Path) -> None:
    p = tmp_path / "big.bin"
    p.write_bytes(b"a" * (2 * binance.CHUNK_BYTES + 7))
    assert sha256_file(p) == hashlib.sha256(p.read_bytes()).hexdigest()


class FakeResponse(io.BytesIO):
    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def test_fetch_to_file_streams_and_leaves_no_part_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = b"x" * (3 * binance.CHUNK_BYTES + 5)
    monkeypatch.setattr(binance, "urlopen", lambda req, timeout: FakeResponse(data))
    dest = tmp_path / "sub" / "file.zip"
    assert fetch_to_file("https://example.invalid/file.zip", dest) == len(data)
    assert dest.read_bytes() == data
    assert not (tmp_path / "sub" / "file.zip.part").exists()


def test_interrupted_download_leaves_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Broken(FakeResponse):
        def read(self, size: int | None = -1) -> bytes:
            raise ConnectionResetError("dropped")

    monkeypatch.setattr(binance, "urlopen", lambda req, timeout: Broken(b""))
    dest = tmp_path / "file.zip"
    with pytest.raises(ConnectionResetError):
        fetch_to_file("https://example.invalid/file.zip", dest)
    assert list(tmp_path.iterdir()) == []


def test_run_downloads_summary_and_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    files = plan_klines(["BTCUSDT"], "1h", Month(2026, 6), Month(2026, 8), tmp_path)
    outcomes = iter(
        [
            (DownloadStatus.DOWNLOADED, "1.0 MB"),
            (DownloadStatus.NOT_FOUND, "404"),
            (DownloadStatus.FAILED, "URLError"),
        ]
    )
    monkeypatch.setattr(binance, "download_file", lambda f, retries: next(outcomes))
    assert run_downloads(files) == 1
    out = capsys.readouterr().out
    assert "[1/3] downloaded" in out and "[3/3] failed" in out
    assert "done: 1 downloaded, 0 skipped, 1 not-found, 1 failed" in out
