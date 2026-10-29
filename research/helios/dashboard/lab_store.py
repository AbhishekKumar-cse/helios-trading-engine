"""Durable bounded development jobs; independent of the promotion/PAPER registry."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from helios.dashboard.lab_templates import expand
from helios.dashboard.nse_backtest import DatasetChoice, NseOptions, datasets
from helios.data.equities import sha256

TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "INTERRUPTED"}
MAX_JOBS = 12


def now() -> str:
    return datetime.now(UTC).isoformat()


def fingerprint(root: Path) -> str:
    """All Python/runtime configuration, without credentials or market observation values."""
    files = [
        *sorted((root / "research/helios").rglob("*.py")),
        root / "pyproject.toml",
        root / "uv.lock",
    ]
    body = "\n".join(f"{p.relative_to(root).as_posix()} {sha256(p)}" for p in files if p.is_file())
    return hashlib.sha256(body.encode()).hexdigest()


@contextmanager
def database(root: Path) -> Iterator[sqlite3.Connection]:
    directory = root / "local_state/research_lab"
    directory.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(directory / "tasks.sqlite3", timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("""CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY,batch_id TEXT NOT NULL,request_hash TEXT UNIQUE NOT NULL,
        status TEXT NOT NULL,spec_json TEXT NOT NULL,created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,owner TEXT,heartbeat TEXT,progress REAL DEFAULT 0,
        message TEXT DEFAULT '',cancel_requested INTEGER DEFAULT 0,result_path TEXT)""")
    connection.commit()
    try:
        yield connection
    finally:
        connection.close()


def jobs(root: Path) -> list[dict[str, Any]]:
    with database(root) as connection:
        return [
            dict(row)
            for row in connection.execute("SELECT * FROM jobs ORDER BY created_at DESC,id")
        ]


def enqueue(
    root: Path,
    dataset: DatasetChoice,
    options: list[NseOptions],
    *,
    hypothesis: str,
    template: str,
    field: str,
    expected_source: str | None = None,
) -> tuple[str, list[str], int]:
    if not 15 <= len(hypothesis.strip()) <= 1000:
        raise ValueError("write a hypothesis of 15–1000 characters before queuing")
    if not 1 <= len(options) <= MAX_JOBS:
        raise ValueError(f"a development batch contains 1–{MAX_JOBS} candidates")
    eligible = next(
        (
            d
            for d in datasets(root)
            if d.path.resolve() == dataset.path.resolve() and d.interval == dataset.interval
        ),
        None,
    )
    if eligible is None or eligible.manifest_sha256 != dataset.manifest_sha256:
        raise ValueError("refresh the verified executable dataset selection")
    digest = fingerprint(root)
    if expected_source is not None and digest != expected_source:
        raise ValueError("source changed after the experiment preview")
    batch = "lab_" + uuid4().hex[:16]
    specs = []
    for option in options:
        option = NseOptions.model_validate(option.model_dump())
        if option.symbol not in eligible.symbols or not option.compare_costs:
            raise ValueError("screened instrument and both cost scenarios required")
        expression = expand(template, field, option.lookback, dataset.interval)
        if option.expression != expression:
            raise ValueError("previewed expression differs from queued candidate")
        spec = dict(
            hypothesis=hypothesis.strip(),
            template=template,
            field=field,
            options=option.model_dump(mode="json"),
            interval=dataset.interval,
            dataset=dataset.path.relative_to(root).as_posix(),
            manifest_sha256=dataset.manifest_sha256,
            code_fingerprint=digest,
            purpose="interactive_development",
            eligible=False,
            test_accesses=0,
            registry_writes=0,
            window_unit="completed bars; reset every session",
        )
        payload = json.dumps(spec, sort_keys=True, separators=(",", ":"))
        specs.append((spec, payload, hashlib.sha256(payload.encode()).hexdigest()))
    directory = root / "reports_out/research_lab/protocols" / batch
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "protocol.json").write_text(
        json.dumps(
            dict(
                batch_id=batch,
                created_at=now(),
                candidates=[s for s, _, _ in specs],
                trial_budget=len(specs),
                automatic_selection=False,
                eligible=False,
            ),
            indent=2,
        )
        + "\n"
    )
    ids, reused = [], 0
    with database(root) as connection:
        connection.execute("BEGIN IMMEDIATE")
        for _, payload, request_hash in specs:
            old = connection.execute(
                "SELECT id,status FROM jobs WHERE request_hash=?", (request_hash,)
            ).fetchone()
            if old:
                ids.append(old["id"])
                reused += 1
                continue
            job_id = "job_" + uuid4().hex[:16]
            created = now()
            connection.execute(
                """INSERT INTO jobs
                (id,batch_id,request_hash,status,spec_json,created_at,updated_at)
                VALUES (?,?,?,'QUEUED',?,?,?)""",
                (job_id, batch, request_hash, payload, created, created),
            )
            ids.append(job_id)
        connection.commit()
    return batch, ids, reused


def claim(root: Path, owner: str) -> dict[str, Any] | None:
    """One local execution slot. Separate worker processes cannot double-claim a job."""
    with database(root) as connection:
        connection.execute("BEGIN IMMEDIATE")
        if connection.execute("SELECT 1 FROM jobs WHERE status='RUNNING' LIMIT 1").fetchone():
            connection.rollback()
            return None
        row = connection.execute(
            "SELECT * FROM jobs WHERE status='QUEUED' ORDER BY created_at,id LIMIT 1"
        ).fetchone()
        if row is None:
            connection.rollback()
            return None
        connection.execute(
            (
                "UPDATE jobs SET status='RUNNING',owner=?,heartbeat=?,updated_at=? "
                "WHERE id=? AND status='QUEUED'"
            ),
            (owner, now(), now(), row["id"]),
        )
        connection.commit()
        return dict(row) | {"owner": owner, "status": "RUNNING"}


def pulse(
    root: Path,
    job_id: str,
    owner: str,
    *,
    progress: float | None = None,
    message: str | None = None,
) -> bool:
    with database(root) as connection:
        row = connection.execute(
            "SELECT cancel_requested FROM jobs WHERE id=? AND owner=? AND status='RUNNING'",
            (job_id, owner),
        ).fetchone()
        if row is None or row[0]:
            return False
        if progress is None:
            connection.execute(
                (
                    "UPDATE jobs SET heartbeat=?,updated_at=? WHERE id=? AND owner=? AND "
                    "status='RUNNING'"
                ),
                (now(), now(), job_id, owner),
            )
        else:
            connection.execute(
                (
                    "UPDATE jobs SET heartbeat=?,updated_at=?,progress=?,message=? WHERE "
                    "id=? AND owner=? AND status='RUNNING'"
                ),
                (now(), now(), max(0, min(1, progress)), message or "", job_id, owner),
            )
        connection.commit()
        return True


def finish(
    root: Path,
    job_id: str,
    owner: str,
    status: str,
    *,
    result_path: str | None = None,
    message: str = "",
) -> bool:
    if status not in TERMINAL:
        raise ValueError("terminal status required")
    with database(root) as connection:
        # Cancellation wins a race with completion; accepted artifacts remain retained.
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT cancel_requested FROM jobs WHERE id=? AND owner=? AND status='RUNNING'",
            (job_id, owner),
        ).fetchone()
        if row is None:
            return False
        if row[0]:
            status = "CANCELLED"
        changed = connection.execute(
            (
                "UPDATE jobs SET "
                "status=?,updated_at=?,heartbeat=?,result_path=?,message=?,"
                "progress=CASE WHEN ?='COMPLETED' THEN 1 ELSE progress END "
                "WHERE id=? AND owner=? AND status='RUNNING'"
            ),
            (status, now(), now(), result_path, message, status, job_id, owner),
        ).rowcount
        connection.commit()
        return bool(changed)


def cancel(root: Path, job_id: str) -> None:
    with database(root) as connection:
        connection.execute(
            (
                "UPDATE jobs SET status=CASE WHEN status='QUEUED' THEN 'CANCELLED' "
                "ELSE status END,cancel_requested=1,updated_at=? WHERE id=? AND status "
                "IN ('QUEUED','RUNNING')"
            ),
            (now(), job_id),
        )
        connection.commit()


def interrupt_stale(root: Path, *, seconds: int = 60) -> int:
    """Explicit operator reconciliation; interrupted jobs are never automatically requeued."""
    if seconds < 60:
        raise ValueError("at least sixty seconds without a worker heartbeat required")
    with database(root) as connection:
        stale = [
            row["id"]
            for row in connection.execute("SELECT id,heartbeat FROM jobs WHERE status='RUNNING'")
            if row["heartbeat"]
            and (datetime.now(UTC) - datetime.fromisoformat(row["heartbeat"])).total_seconds()
            > seconds
        ]
        for job_id in stale:
            connection.execute(
                (
                    "UPDATE jobs SET status='INTERRUPTED',updated_at=?,message='Worker "
                    "heartbeat lost; retained artifacts need review' WHERE id=? AND "
                    "status='RUNNING'"
                ),
                (now(), job_id),
            )
        connection.commit()
        return len(stale)
