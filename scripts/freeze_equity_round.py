"""Run a preregistered round from an immutable local source copy while work continues.

The copy is a research artifact inside reports_out, not a Git branch/worktree.
Market data and output paths point at the existing workspace. Credentials are
loaded privately from the workspace .env and never copied into the source archive.
"""

import argparse
import os
import re
import shutil
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--round-id", required=True)
    parser.add_argument("--interval", choices=("1h", "1m"), default="1h")
    parser.add_argument(
        "--suite", choices=("baseline", "reference", "extended", "all"), default="baseline"
    )
    parser.add_argument("--research-symbols", nargs="*", default=[])
    parser.add_argument("--workers", type=int, choices=(1, 2, 3, 4), default=1)
    parser.add_argument("--repaired", action="store_true")
    args = parser.parse_args()
    source_snapshot = args.snapshot.resolve()
    if not re.fullmatch(r"nse_[a-z0-9_]{3,32}", args.round_id):
        raise ValueError("invalid immutable research round ID")
    repo = Path(__file__).resolve().parents[1]
    runtime = repo / "reports_out/equity_runtime" / args.round_id
    runtime.mkdir(parents=True, exist_ok=False)
    for source in [
        *sorted((repo / "research/helios").rglob("*.py")),
        *sorted((repo / "configs/equities").glob("*.yaml")),
        repo / "pyproject.toml",
        repo / "uv.lock",
    ]:
        target = runtime / source.relative_to(repo)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    (runtime / "reports_out").symlink_to(repo / "reports_out", target_is_directory=True)
    sys.path.insert(0, str(runtime / "research"))
    from sqlalchemy import create_engine

    from helios.common.db import DatabaseSettings
    from helios.equities import pipeline

    assert Path(pipeline.__file__).is_relative_to(runtime)
    engine = create_engine(DatabaseSettings(_env_file=repo / ".env").url(), pool_pre_ping=True)
    print(f"Frozen research runtime: {runtime}", flush=True)
    # All paths below are absolute. Avoid OneDrive/WSL invalidating the inherited
    # current-directory inode while Git and multiprocessing launch subprocesses.
    os.chdir("/tmp")
    pipeline.run_round(
        source_snapshot,
        args.round_id,
        engine=engine,
        interval=args.interval,
        suite=args.suite,
        research_symbols=tuple(args.research_symbols),
        workers=args.workers,
        repaired=args.repaired,
    )


if __name__ == "__main__":
    main()
