"""Tests for data snapshots (step 059).

A small Parquet store is built from the committed fixture zips. Database tests run inside a
transaction that is rolled back, and skip when no database is reachable.
"""

import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError
from sqlalchemy import Connection, text

from helios.common import db
from helios.data.bars import BarBuildError, build_bars
from helios.data.snapshots import (
    Snapshot,
    SnapshotFile,
    compute_snapshot_id,
    describe_bars,
    load_manifest,
    register_snapshot,
    write_manifest,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def store(tmp_path: Path) -> Path:
    """Bars for two coins: 3 hourly bars in 2024-12 and 3 in 2025-01, so 2 files each."""
    raw = tmp_path / "raw" / "binance" / "spot" / "klines_1h"
    raw.mkdir(parents=True)
    for symbol in ("BTCUSDT", "ETHUSDT"):
        for month in ("2024-12", "2025-01"):
            shutil.copy(FIXTURES / f"BTCUSDT-1h-{month}.zip", raw / f"{symbol}-1h-{month}.zip")
    out = tmp_path / "bars"
    for symbol in ("BTCUSDT", "ETHUSDT"):
        build_bars(symbol, "1h", tmp_path / "raw", out)
    return out


# ---------------------------------------------------------------- the id


def test_the_id_is_a_sha256() -> None:
    files = [SnapshotFile("a.parquet", "ab" * 32, 10)]
    snapshot_id = compute_snapshot_id(files)
    assert len(snapshot_id) == 64
    assert set(snapshot_id) <= set("0123456789abcdef")


def test_the_same_files_always_give_the_same_id() -> None:
    files = [SnapshotFile("a.parquet", "ab" * 32, 10), SnapshotFile("b.parquet", "cd" * 32, 20)]
    assert compute_snapshot_id(files) == compute_snapshot_id(list(reversed(files)))


def test_one_changed_checksum_changes_the_id() -> None:
    before = compute_snapshot_id([SnapshotFile("a.parquet", "ab" * 32, 10)])
    after = compute_snapshot_id([SnapshotFile("a.parquet", "ac" * 32, 10)])
    assert before != after


def test_an_extra_file_changes_the_id() -> None:
    one = [SnapshotFile("a.parquet", "ab" * 32, 10)]
    two = [*one, SnapshotFile("b.parquet", "cd" * 32, 20)]
    assert compute_snapshot_id(one) != compute_snapshot_id(two)


def test_an_empty_snapshot_is_refused() -> None:
    with pytest.raises(BarBuildError, match="at least one file"):
        compute_snapshot_id([])


# ---------------------------------------------------------------- describing real bars


def test_describe_counts_files_rows_and_range(store: Path) -> None:
    snapshot = describe_bars(["BTCUSDT", "ETHUSDT"], "1h", store)
    assert snapshot.file_count == 4  # 2 coins x 2 years
    assert snapshot.row_count == 12  # 2 coins x 6 bars
    assert snapshot.symbols == ["BTCUSDT", "ETHUSDT"]
    assert snapshot.interval == "1h"
    assert snapshot.first_open_time == 1733011200000000  # 2024-12-01 00:00 UTC
    assert snapshot.total_bytes > 0
    assert len(snapshot.code_commit) == 40


def test_describing_the_same_store_twice_gives_the_same_id(store: Path) -> None:
    assert (
        describe_bars(["BTCUSDT"], "1h", store).snapshot_id
        == describe_bars(["BTCUSDT"], "1h", store).snapshot_id
    )


def test_different_coins_give_different_ids(store: Path) -> None:
    assert (
        describe_bars(["BTCUSDT"], "1h", store).snapshot_id
        != describe_bars(["BTCUSDT", "ETHUSDT"], "1h", store).snapshot_id
    )


def test_changing_one_file_changes_the_id(store: Path) -> None:
    """Rewrite one file with one different price: still valid Parquet, different bytes."""
    before = describe_bars(["BTCUSDT"], "1h", store)
    target = store / "source=binance/interval=1h/symbol=BTCUSDT/year=2025/bars.parquet"
    frame = pd.read_parquet(target)
    frame.loc[0, "close"] = frame.loc[0, "close"] + 1
    frame.to_parquet(target, engine="pyarrow", compression="zstd", index=False)

    after = describe_bars(["BTCUSDT"], "1h", store)
    assert after.snapshot_id != before.snapshot_id
    assert after.row_count == before.row_count  # same rows, different content
    assert {f.path for f in after.files} == {f.path for f in before.files}


def test_paths_are_relative_so_the_id_does_not_depend_on_the_folder(store: Path) -> None:
    snapshot = describe_bars(["BTCUSDT"], "1h", store)
    assert all(not f.path.startswith("/") and ":" not in f.path for f in snapshot.files)
    assert snapshot.files[0].path.startswith("source=binance/interval=1h/")


def test_a_coin_without_bars_is_refused(store: Path) -> None:
    with pytest.raises(BarBuildError, match="no 1h bars for SOLUSDT"):
        describe_bars(["SOLUSDT"], "1h", store)


def test_no_symbols_is_refused(store: Path) -> None:
    with pytest.raises(BarBuildError, match="at least one symbol"):
        describe_bars([], "1h", store)


# ---------------------------------------------------------------- the manifest


def test_manifest_lists_every_file(store: Path, tmp_path: Path) -> None:
    snapshot = describe_bars(["BTCUSDT"], "1h", store)
    path = write_manifest(snapshot, tmp_path / "snapshots")
    assert path.name == f"{snapshot.snapshot_id}.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert len(saved["files"]) == 2
    assert all(len(f["sha256"]) == 64 for f in saved["files"])


def test_manifest_round_trip(store: Path, tmp_path: Path) -> None:
    snapshot = describe_bars(["BTCUSDT"], "1h", store)
    write_manifest(snapshot, tmp_path / "snapshots")
    back = load_manifest(snapshot.snapshot_id, tmp_path / "snapshots")
    assert back == snapshot


def test_a_missing_manifest_is_refused(tmp_path: Path) -> None:
    with pytest.raises(BarBuildError, match="no manifest at"):
        load_manifest("0" * 64, tmp_path)


# ---------------------------------------------------------------- the database row


@pytest.fixture
def connection() -> Iterator[Connection]:
    try:
        db.get_settings()
    except ValidationError:
        pytest.skip("database settings not configured (no .env / POSTGRES_* variables)")
    try:
        conn = db.get_engine().connect()
    except Exception as exc:  # noqa: BLE001 - any failure here means "no database"
        pytest.skip(f"database not reachable: {type(exc).__name__}")
    transaction = conn.begin()
    try:
        yield conn
    finally:
        transaction.rollback()
        conn.close()


def test_the_row_is_stored(store: Path, connection: Connection) -> None:
    snapshot = describe_bars(["BTCUSDT"], "1h", store)
    assert register_snapshot(connection, snapshot) is True
    row = connection.execute(
        text(
            "SELECT source, interval, symbols, row_count, file_count, first_open_time "
            "FROM data_snapshots WHERE snapshot_id = :id"
        ),
        {"id": snapshot.snapshot_id},
    ).one()
    assert (row.source, row.interval) == ("binance", "1h")
    assert row.symbols == ["BTCUSDT"]
    assert (row.row_count, row.file_count) == (6, 2)
    assert row.first_open_time == snapshot.first_open_time


def test_registering_twice_does_not_duplicate(store: Path, connection: Connection) -> None:
    """A snapshot is never updated: the same id always means the same bytes."""
    snapshot = describe_bars(["BTCUSDT"], "1h", store)
    assert register_snapshot(connection, snapshot) is True
    assert register_snapshot(connection, snapshot) is False
    count = connection.execute(
        text("SELECT count(*) FROM data_snapshots WHERE snapshot_id = :id"),
        {"id": snapshot.snapshot_id},
    ).scalar_one()
    assert count == 1


def test_an_experiment_can_point_at_a_snapshot(store: Path, connection: Connection) -> None:
    snapshot = describe_bars(["BTCUSDT"], "1h", store)
    register_snapshot(connection, snapshot)
    connection.execute(
        text(
            "INSERT INTO experiments (kind, hypothesis, author, snapshot_id) "
            "VALUES ('alpha', 'hourly momentum beats holding, after costs', 'abhishek', :id)"
        ),
        {"id": snapshot.snapshot_id},
    )
    used = connection.execute(
        text("SELECT snapshot_id FROM experiments ORDER BY experiment_id DESC LIMIT 1")
    ).scalar_one()
    assert used == snapshot.snapshot_id


def test_a_snapshot_with_no_rows_is_refused_by_the_database(connection: Connection) -> None:
    empty = Snapshot(
        snapshot_id="0" * 64,
        source="binance",
        interval="1h",
        symbols=["BTCUSDT"],
        first_open_time=1,
        last_open_time=2,
        file_count=1,
        row_count=0,  # the database check requires more than zero
        total_bytes=1,
        code_commit="a" * 40,
        files=[SnapshotFile("a.parquet", "ab" * 32, 1)],
    )
    with pytest.raises(Exception, match="data_snapshots_rows_positive"):
        register_snapshot(connection, empty)
