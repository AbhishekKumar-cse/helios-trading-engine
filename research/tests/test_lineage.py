"""Tests for run lineage (step 028). Each test uses its own temporary git repo."""

import dataclasses
import subprocess
from pathlib import Path

import pytest

from helios.common.config import HeliosConfig, config_hash
from helios.common.lineage import LineageError, RunContext, git_commit, git_is_dirty


class DemoConfig(HeliosConfig):
    sharpe_min: float


CFG = DemoConfig(sharpe_min=1.0)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            *args,
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    (tmp_path / "code.py").write_text("x = 1\n", encoding="utf-8")
    git(tmp_path, "add", "code.py")
    git(tmp_path, "commit", "-q", "-m", "first")
    return tmp_path


def test_clean_repo_capture(repo: Path) -> None:
    ctx = RunContext.capture(CFG, "snap-001", 42, reported=True, repo=repo)
    assert ctx.code_commit == git(repo, "rev-parse", "HEAD")
    assert len(ctx.code_commit) == 40
    assert ctx.dirty is False
    assert ctx.config_hash == config_hash(CFG)
    assert ctx.data_snapshot_id == "snap-001"
    assert ctx.seed == 42
    assert ctx.created_at.tzinfo is not None


def test_modified_file_makes_tree_dirty(repo: Path) -> None:
    (repo / "code.py").write_text("x = 2\n", encoding="utf-8")
    assert git_is_dirty(repo) is True
    ctx = RunContext.capture(CFG, "snap-001", 42, repo=repo)
    assert ctx.dirty is True


def test_untracked_file_makes_tree_dirty(repo: Path) -> None:
    (repo / "new.py").write_text("y = 1\n", encoding="utf-8")
    assert git_is_dirty(repo) is True


def test_ignored_file_keeps_tree_clean(repo: Path) -> None:
    (repo / ".gitignore").write_text("*.log\n", encoding="utf-8")
    git(repo, "add", ".gitignore")
    git(repo, "commit", "-q", "-m", "ignore logs")
    (repo / "run.log").write_text("noise\n", encoding="utf-8")
    assert git_is_dirty(repo) is False


def test_reported_run_refuses_dirty_tree(repo: Path) -> None:
    (repo / "code.py").write_text("x = 3\n", encoding="utf-8")
    with pytest.raises(LineageError, match="clean git tree"):
        RunContext.capture(CFG, "snap-001", 42, reported=True, repo=repo)


def test_commit_changes_after_new_commit(repo: Path) -> None:
    before = git_commit(repo)
    (repo / "code.py").write_text("x = 4\n", encoding="utf-8")
    git(repo, "commit", "-q", "-am", "second")
    assert git_commit(repo) != before


def test_not_a_git_repo(tmp_path: Path) -> None:
    with pytest.raises(LineageError, match="failed"):
        RunContext.capture(CFG, "snap-001", 42, repo=tmp_path)


@pytest.mark.parametrize("seed", [-1, 1.5, True, "7"])
def test_bad_seed_is_rejected(repo: Path, seed: object) -> None:
    with pytest.raises(LineageError, match="seed"):
        RunContext.capture(CFG, "snap-001", seed, repo=repo)  # type: ignore[arg-type]


def test_empty_snapshot_id_is_rejected(repo: Path) -> None:
    with pytest.raises(LineageError, match="data_snapshot_id"):
        RunContext.capture(CFG, "  ", 42, repo=repo)


def test_run_context_is_frozen(repo: Path) -> None:
    ctx = RunContext.capture(CFG, "snap-001", 42, repo=repo)
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.seed = 7  # type: ignore[misc]
