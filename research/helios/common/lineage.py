"""Run lineage (step 028).

Every stored result must say exactly what produced it: the code version (git commit),
whether the code had uncommitted changes, the config fingerprint, the data snapshot and
the random seed. With these five values any result can be reproduced later.

Runs whose results will be *reported* must start from a clean git tree; otherwise the
commit hash would not describe the code that actually ran.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from helios.common.config import config_hash

# research/helios/common/lineage.py -> parents[3] is the project root (the git repo)
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class LineageError(Exception):
    """Raised when lineage cannot be captured, or a reported run has uncommitted changes."""


def _git(repo: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise LineageError("git is not installed or not on PATH") from exc
    except subprocess.CalledProcessError as exc:
        raise LineageError(f"git {' '.join(args)} failed in {repo}: {exc.stderr.strip()}") from exc
    return result.stdout.strip()


@lru_cache(maxsize=8)
def git_commit(repo: Path = PROJECT_ROOT) -> str:
    """Full hash of the commit currently checked out."""
    return _git(repo, "rev-parse", "HEAD")


@lru_cache(maxsize=8)
def git_is_dirty(repo: Path = PROJECT_ROOT) -> bool:
    """True if there are uncommitted changes or new files that git is not ignoring."""
    return _git(repo, "status", "--porcelain") != ""


def forget_git_state() -> None:
    """Read the repository state again next time.

    Both answers above are cached for the life of the process. Two reasons: asking git is
    slow here (the repository lives on the Windows filesystem, and each call from Ubuntu
    costs most of a second), and a long run should describe the code it *started* with
    rather than notice an edit made while it was running. Anything that changes the
    repository on purpose — a test, a tool — calls this to clear the answers.
    """
    git_commit.cache_clear()
    git_is_dirty.cache_clear()


@dataclass(frozen=True)
class RunContext:
    """The five values that identify how a result was produced (plus when)."""

    code_commit: str
    dirty: bool
    config_hash: str
    data_snapshot_id: str
    seed: int
    created_at: datetime

    @classmethod
    def capture(
        cls,
        config: BaseModel,
        data_snapshot_id: str,
        seed: int,
        *,
        reported: bool = False,
        repo: Path = PROJECT_ROOT,
    ) -> RunContext:
        """Record lineage for a run. `reported=True` refuses to run on a dirty tree."""
        if not data_snapshot_id.strip():
            raise LineageError("data_snapshot_id must not be empty")
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise LineageError(f"seed must be a non-negative integer, got {seed!r}")

        commit = git_commit(repo)
        dirty = git_is_dirty(repo)
        if reported and dirty:
            raise LineageError(
                "reported runs need a clean git tree: commit or stash your changes first "
                "(see `git status`)"
            )

        return cls(
            code_commit=commit,
            dirty=dirty,
            config_hash=config_hash(config),
            data_snapshot_id=data_snapshot_id,
            seed=seed,
            created_at=datetime.now(UTC),
        )
