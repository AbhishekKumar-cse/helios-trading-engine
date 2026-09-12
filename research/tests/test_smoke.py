"""Smoke test: proves pytest runs and the helios package is importable (step 017)."""

import helios


def test_smoke() -> None:
    assert 1 + 1 == 2
    assert helios.__version__ == "0.1.0"
