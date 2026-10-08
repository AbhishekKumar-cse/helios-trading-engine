"""Step 083: disk round trips, availability, year boundaries and the real CLI."""

import json
import subprocess
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from helios.data.bars import BarBuildError, write_bars
from helios.data.binance import sha256_file
from helios.data.klines import interval_us
from helios.features.registry import REGISTRY, FeatureError
from helios.features.runner import compute_features
from helios.features.store import AVAILABILITY_PREFIX, build_features

PROJECT = Path(__file__).resolve().parents[2]


def bars(n: int = 200, interval: str = "1h") -> pd.DataFrame:
    t = np.arange(n)
    start = pd.Timestamp("2024-12-31T22:00:00Z").value // 1000
    price = 100 + t * 0.1 + np.sin(t)
    volume = 10.0 + t % 7
    return pd.DataFrame(
        {
            "open_time": start + t * interval_us(interval),
            "close_time": start + (t + 1) * interval_us(interval) - 1,
            "open": price,
            "high": price + 2,
            "low": price - 2,
            "close": price + 0.1,
            "volume": volume,
            "quote_volume": volume * price,
            "trades": 1 + t % 11,
            "taker_buy_base": volume * (0.1 + 0.1 * (t % 8)),
            "taker_buy_quote": volume * price * (0.1 + 0.1 * (t % 8)),
        }
    )


def read_features(files: list[Path]) -> pd.DataFrame:
    return pd.concat([pd.read_parquet(path) for path in files], ignore_index=True)


@pytest.mark.parametrize("interval", ["1h", "1m"])
def test_round_trip_matches_runner_and_keeps_masks(tmp_path: Path, interval: str) -> None:
    source = bars(200, interval)
    write_bars(source, "BTCUSDT", interval, tmp_path / "bars")
    result = build_features("BTCUSDT", interval, tmp_path / "bars", tmp_path / "features")
    expected = compute_features(source, interval)
    back = read_features(result.files_written)
    assert result.rows == 200 and result.off_grid_rows == 0
    assert back["open_time"].tolist() == source["open_time"].tolist()
    pd.testing.assert_frame_equal(back[expected.names], expected.values)
    pd.testing.assert_frame_equal(
        back[[AVAILABILITY_PREFIX + n for n in expected.names]],
        expected.available.add_prefix(AVAILABILITY_PREFIX),
    )
    assert all(back[AVAILABILITY_PREFIX + name].dtype == bool for name in expected.names)
    assert back["open_time"].dtype == np.dtype("int64")
    assert len(back.columns) == 1 + 2 * len(REGISTRY)
    assert (
        pq.ParquetFile(result.files_written[0]).metadata.row_group(0).column(0).compression
        == "ZSTD"
    )


def test_year_partition_does_not_restart_warmup_and_is_hive_readable(tmp_path: Path) -> None:
    write_bars(bars(), "BTCUSDT", "1h", tmp_path / "bars")
    result = build_features("BTCUSDT", "1h", tmp_path / "bars", tmp_path / "features")
    assert [p.parent.name for p in result.files_written] == ["year=2024", "year=2025"]
    january = pd.read_parquet(result.files_written[1])
    # Jan 1's first bar can use December's preceding close.
    assert january["available__log_return_1"].iloc[0]
    assert not january["available__log_return_24"].iloc[0]
    with duckdb.connect() as connection:
        frame = connection.execute(
            "SELECT symbol, interval, feature_set, count(*) AS n FROM read_parquet(?, "
            "hive_partitioning=true) GROUP BY ALL",
            [
                str(
                    tmp_path
                    / "features"
                    / "feature_set=*"
                    / "interval=*"
                    / "symbol=*"
                    / "year=*"
                    / "features.parquet"
                )
            ],
        ).df()
    assert frame.iloc[0].tolist() == ["BTCUSDT", "1h", "v1", 200]


def test_off_grid_and_gaps_are_retained_unavailable_without_changing_source(tmp_path: Path) -> None:
    source = bars().drop(index=5).reset_index(drop=True)
    source.loc[10, "open_time"] += 1  # neither delete nor round this observation
    paths = write_bars(source, "BTCUSDT", "1h", tmp_path / "bars")
    hashes = [sha256_file(p) for p in paths]
    result = build_features("BTCUSDT", "1h", tmp_path / "bars", tmp_path / "features")
    back = read_features(result.files_written)
    assert result.rows == 199 and result.off_grid_rows == 1
    assert back["open_time"].tolist() == source["open_time"].tolist()
    assert back.loc[10, REGISTRY.names()].isna().all()
    assert not back.loc[10, [AVAILABILITY_PREFIX + n for n in REGISTRY.names()]].any()
    assert not back["available__log_return_4"].iloc[5:9].any()
    assert not back["available__log_return_1"].iloc[11]
    assert [sha256_file(p) for p in paths] == hashes


def test_manifest_pins_config_input_output_and_rebuild_is_repeatable(tmp_path: Path) -> None:
    write_bars(bars(), "BTCUSDT", "1h", tmp_path / "bars")
    first = build_features("BTCUSDT", "1h", tmp_path / "bars", tmp_path / "features")
    data = json.loads(first.manifest.read_text())
    assert data["rows"] == 200 and data["off_grid_rows"] == 0
    assert data["lineage"]["data_snapshot_id"] == data["input_snapshot"]["snapshot_id"]
    assert len(data["lineage"]["code_commit"]) == 40
    assert len(data["lineage"]["config_hash"]) == 64
    assert isinstance(data["lineage"]["dirty"], bool)
    assert data["lineage"]["seed"] == 0
    assert [s["name"] for s in data["config"]["features"]] == REGISTRY.names()
    assert data["config"]["off_grid_policy"] == "retain_unavailable"
    assert data["availability"]["log_return_24"] == pytest.approx(176 / 200)
    for entry, path in zip(data["files"], first.files_written, strict=True):
        assert first.manifest.parent / entry["path"] == path
        assert entry["sha256"] == sha256_file(path)
    rebuilt = build_features("BTCUSDT", "1h", tmp_path / "bars", tmp_path / "features")
    again = json.loads(rebuilt.manifest.read_text())
    assert again["files"] == data["files"]
    assert again["lineage"]["config_hash"] == data["lineage"]["config_hash"]
    assert not list((tmp_path / "features").rglob("*.part"))


def test_symbols_are_computed_independently(tmp_path: Path) -> None:
    a = bars()
    b = bars()
    b["quote_volume"] *= 100
    for symbol, frame in [("BTCUSDT", a), ("ETHUSDT", b)]:
        write_bars(frame, symbol, "1h", tmp_path / "bars")
    first = build_features("BTCUSDT", "1h", tmp_path / "bars", tmp_path / "features")
    second = build_features("ETHUSDT", "1h", tmp_path / "bars", tmp_path / "features")
    np.testing.assert_allclose(
        read_features(second.files_written)["dollar_volume"],
        read_features(first.files_written)["dollar_volume"] * 100,
    )


def test_all_off_grid_fails_without_creating_feature_files(tmp_path: Path) -> None:
    frame = bars(3)
    frame["open_time"] += 1
    write_bars(frame, "BTCUSDT", "1h", tmp_path / "bars")
    with pytest.raises(FeatureError, match="no on-grid"):
        build_features("BTCUSDT", "1h", tmp_path / "bars", tmp_path / "features")
    assert not (tmp_path / "features").exists()


def test_missing_source_fails_without_creating_feature_files(tmp_path: Path) -> None:
    with pytest.raises(BarBuildError, match="no 1h bars"):
        build_features("BTCUSDT", "1h", tmp_path / "bars", tmp_path / "features")
    assert not (tmp_path / "features").exists()


def test_stale_partitions_are_refused_before_overwriting(tmp_path: Path) -> None:
    write_bars(bars(), "BTCUSDT", "1h", tmp_path / "bars")
    root = tmp_path / "features" / "feature_set=v1" / "interval=1h" / "symbol=BTCUSDT"
    stale = root / "year=2000" / "features.parquet"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"existing data")
    with pytest.raises(FeatureError, match="stale"):
        build_features("BTCUSDT", "1h", tmp_path / "bars", tmp_path / "features")
    assert stale.read_bytes() == b"existing data"
    assert not (root / "manifest.json").exists()


@pytest.mark.parametrize("symbol", ["../BTCUSDT", "", "btc/usdt"])
def test_unsafe_symbol_is_refused(tmp_path: Path, symbol: str) -> None:
    with pytest.raises(FeatureError, match="invalid symbol"):
        build_features(symbol, "1h", tmp_path / "bars", tmp_path / "features")


def test_cli_defaults_to_whole_universe_and_reports_missing_coin(tmp_path: Path) -> None:
    # Omit one configured symbol deliberately: the rest must still export and exit nonzero.
    for symbol in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]:
        write_bars(bars(3), symbol, "1h", tmp_path / "bars")
    run = subprocess.run(
        [
            sys.executable,
            str(PROJECT / "scripts" / "build_features.py"),
            "--interval",
            "1h",
            "--bars-dir",
            str(tmp_path / "bars"),
            "--out-dir",
            str(tmp_path / "features"),
        ],
        cwd=PROJECT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 1
    assert "XRPUSDT" in run.stderr
    assert len(list((tmp_path / "features").rglob("manifest.json"))) == 4
    assert "off-grid rows retained unavailable: 0" in run.stdout


def test_cli_minute_single_symbol(tmp_path: Path) -> None:
    write_bars(bars(3, "1m"), "BTCUSDT", "1m", tmp_path / "bars")
    run = subprocess.run(
        [
            sys.executable,
            str(PROJECT / "scripts" / "build_features.py"),
            "--interval",
            "1m",
            "--symbol",
            "BTCUSDT",
            "--bars-dir",
            str(tmp_path / "bars"),
            "--out-dir",
            str(tmp_path / "features"),
        ],
        cwd=PROJECT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    assert "BTCUSDT 1m: 3 rows" in run.stdout
