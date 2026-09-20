"""Record exactly which data a result was computed from (step 059).

A result is only believable if you can say *which bytes* produced it. A snapshot answers
that: it lists every Parquet file that makes up a dataset, with each file's SHA-256, and
reduces them to one id.

    snapshot_id = sha256 of the sorted lines "<relative path>  <file sha256>"

Two consequences follow from that definition:

- the id is **deterministic** — the same files always give the same id, on any machine;
- the id is **sensitive** — changing one byte of one file changes the id completely, so a
  result can never silently point at different data than it was computed from.

The database row (`data_snapshots`, migration 001) holds the summary. The full file list is
written next to the data as `data/processed/snapshots/<snapshot_id>.json`, because the
summary alone cannot tell you *which* file changed.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import duckdb
from sqlalchemy import Connection, text

from helios.common.lineage import git_commit
from helios.data.bars import DEFAULT_OUT_DIR, BarBuildError
from helios.data.binance import sha256_file
from helios.data.klines import interval_us

SNAPSHOT_DIR = DEFAULT_OUT_DIR.parent / "snapshots"


@dataclass(frozen=True)
class SnapshotFile:
    """One file inside a snapshot."""

    path: str  # relative to the bars folder, so the id does not depend on where the repo sits
    sha256: str
    bytes: int


@dataclass(frozen=True)
class Snapshot:
    """A dataset, pinned down: which files, how many rows, and over what period."""

    snapshot_id: str
    source: str
    interval: str
    symbols: list[str]
    first_open_time: int
    last_open_time: int
    file_count: int
    row_count: int
    total_bytes: int
    code_commit: str
    files: list[SnapshotFile]

    @property
    def first_utc(self) -> datetime:
        return datetime.fromtimestamp(self.first_open_time / 1_000_000, tz=UTC)

    @property
    def last_utc(self) -> datetime:
        return datetime.fromtimestamp(self.last_open_time / 1_000_000, tz=UTC)


def compute_snapshot_id(files: Sequence[SnapshotFile]) -> str:
    """One id for a set of files: sha256 over their sorted paths and checksums."""
    if not files:
        raise BarBuildError("a snapshot must contain at least one file")
    lines = sorted(f"{f.path}  {f.sha256}" for f in files)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def describe_bars(
    symbols: Sequence[str],
    interval: str,
    out_dir: Path = DEFAULT_OUT_DIR,
    source: str = "binance",
) -> Snapshot:
    """Look at the Parquet files for these coins and build the snapshot record."""
    interval_us(interval)
    if not symbols:
        raise BarBuildError("give at least one symbol")

    root = out_dir / f"source={source}" / f"interval={interval}"
    files: list[SnapshotFile] = []
    for symbol in sorted(symbols):
        found = sorted((root / f"symbol={symbol}").glob("year=*/bars.parquet"))
        if not found:
            raise BarBuildError(f"no {interval} bars for {symbol} under {out_dir}")
        files += [
            SnapshotFile(
                path=str(path.relative_to(out_dir)).replace("\\", "/"),
                sha256=sha256_file(path),
                bytes=path.stat().st_size,
            )
            for path in found
        ]

    pattern = str(root / "symbol=*" / "year=*" / "bars.parquet")
    with duckdb.connect() as connection:
        rows, first, last = connection.execute(
            "SELECT count(*), min(open_time), max(open_time) "
            "FROM read_parquet($pattern, hive_partitioning = true) "
            "WHERE symbol IN (SELECT UNNEST($symbols))",
            {"pattern": pattern, "symbols": list(symbols)},
        ).fetchone() or (0, None, None)

    if not rows or first is None or last is None:
        raise BarBuildError(f"the {interval} bars for {sorted(symbols)} contain no rows")

    return Snapshot(
        snapshot_id=compute_snapshot_id(files),
        source=source,
        interval=interval,
        symbols=sorted(symbols),
        first_open_time=int(first),
        last_open_time=int(last),
        file_count=len(files),
        row_count=int(rows),
        total_bytes=sum(f.bytes for f in files),
        code_commit=git_commit(),
        files=files,
    )


def write_manifest(snapshot: Snapshot, snapshot_dir: Path = SNAPSHOT_DIR) -> Path:
    """Save the full file list as JSON, so a changed id can be explained file by file."""
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    path = snapshot_dir / f"{snapshot.snapshot_id}.json"
    path.write_text(json.dumps(asdict(snapshot), indent=2, sort_keys=True), encoding="utf-8")
    return path


INSERT_SNAPSHOT = text("""
INSERT INTO data_snapshots
    (snapshot_id, source, interval, symbols, first_open_time, last_open_time,
     file_count, row_count, total_bytes, code_commit)
VALUES
    (:snapshot_id, :source, :interval, CAST(:symbols AS jsonb), :first_open_time,
     :last_open_time, :file_count, :row_count, :total_bytes, :code_commit)
ON CONFLICT (snapshot_id) DO NOTHING
""")


def register_snapshot(connection: Connection, snapshot: Snapshot) -> bool:
    """Store the snapshot row. Returns True if it was new, False if it already existed.

    A snapshot is **never updated**: the same id always means the same bytes, so re-running
    a build over unchanged data simply finds the row already there.
    """
    result = connection.execute(
        INSERT_SNAPSHOT,
        {
            "snapshot_id": snapshot.snapshot_id,
            "source": snapshot.source,
            "interval": snapshot.interval,
            "symbols": json.dumps(snapshot.symbols),
            "first_open_time": snapshot.first_open_time,
            "last_open_time": snapshot.last_open_time,
            "file_count": snapshot.file_count,
            "row_count": snapshot.row_count,
            "total_bytes": snapshot.total_bytes,
            "code_commit": snapshot.code_commit,
        },
    )
    return result.rowcount == 1


def load_manifest(snapshot_id: str, snapshot_dir: Path = SNAPSHOT_DIR) -> Snapshot:
    """Read a manifest back from disk."""
    path = snapshot_dir / f"{snapshot_id}.json"
    if not path.is_file():
        raise BarBuildError(f"no manifest at {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["files"] = [SnapshotFile(**f) for f in raw["files"]]
    return Snapshot(**raw)
