"""Bounded local BACKTEST worker; no registry promotion, network feeds or PAPER control."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4

from helios.common.lineage import PROJECT_ROOT
from helios.dashboard import lab_store
from helios.dashboard.nse_backtest import NseOptions, datasets, run_backtest


class JobCancelled(RuntimeError):
    """Stop between flat session accounts; never fabricate an exit fill."""


def process_one(root: Path) -> bool:
    owner = uuid4().hex
    job = lab_store.claim(root, owner)
    if job is None:
        return False
    stop, lost = threading.Event(), threading.Event()

    def heartbeat() -> None:
        while not stop.wait(2):
            if not lab_store.pulse(root, job["id"], owner):
                lost.set()
                return

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        spec = json.loads(job["spec_json"])
        if spec["code_fingerprint"] != lab_store.fingerprint(root):
            raise ValueError("Source changed after preview; prepare a new experiment")
        dataset = next(
            (
                d
                for d in datasets(root)
                if d.path.relative_to(root).as_posix() == spec["dataset"]
                and d.interval == spec["interval"]
                and d.manifest_sha256 == spec["manifest_sha256"]
            ),
            None,
        )
        if dataset is None:
            raise ValueError("Frozen dataset no longer matches retained executable inputs")

        def progress(value: float, message: str) -> None:
            if lost.is_set() or not lab_store.pulse(
                root, job["id"], owner, progress=value, message=message
            ):
                raise JobCancelled("Cancellation or ownership loss after a completed flat session")

        progress(0, "Verifying retained data and frozen source")
        output = run_backtest(
            dataset,
            NseOptions.model_validate(spec["options"]),
            output_root=root / "reports_out/research_lab/runs" / job["id"],
            progress=progress,
        )
        lab_store.finish(
            root,
            job["id"],
            owner,
            "COMPLETED",
            result_path=output.relative_to(root).as_posix(),
            message="Both cost scenarios retained · development only",
        )
    except JobCancelled:
        lab_store.finish(
            root,
            job["id"],
            owner,
            "CANCELLED",
            message="Stopped at a flat session boundary; partial receipts retained",
        )
    except Exception as error:
        # Exception messages from providers/settings may contain sensitive values.
        lab_store.finish(
            root,
            job["id"],
            owner,
            "FAILED",
            message=f"{type(error).__name__}: review frozen inputs, source "
            "and retained failure receipts",
        )
    finally:
        stop.set()
        thread.join(timeout=3)
    return True


def start_worker(root: Path = PROJECT_ROOT) -> int:
    directory = root / "local_state/research_lab"
    directory.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "research")
    with (directory / "worker.log").open("ab") as output:
        process = subprocess.Popen(
            [sys.executable, "-m", "helios.dashboard.lab_worker", "--max-jobs", "12"],
            cwd=root,
            env=environment,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return process.pid


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-jobs", type=int, default=12)
    args = parser.parse_args()
    if not 1 <= args.max_jobs <= 12:
        parser.error("one invocation handles at most twelve jobs")
    completed, idle = 0, time.monotonic()
    while completed < args.max_jobs and time.monotonic() - idle < 20:
        if process_one(PROJECT_ROOT):
            completed += 1
            idle = time.monotonic()
        else:
            time.sleep(1)


if __name__ == "__main__":
    main()
