"""Tests for set_seed (step 029)."""

import random

import numpy as np
import pytest

from helios.common.seed import MAX_SEED, set_seed


def draw() -> tuple[list[float], list[float]]:
    return [random.random() for _ in range(5)], np.random.rand(5).tolist()


def test_same_seed_same_numbers() -> None:
    set_seed(42)
    first = draw()
    set_seed(42)
    assert draw() == first


def test_different_seed_different_numbers() -> None:
    set_seed(1)
    first = draw()
    set_seed(2)
    assert draw() != first


def test_returned_generator_is_reproducible() -> None:
    a = set_seed(7).normal(size=5)
    b = set_seed(7).normal(size=5)
    assert np.array_equal(a, b)


@pytest.mark.parametrize("seed", [0, MAX_SEED])
def test_boundary_seeds_are_accepted(seed: int) -> None:
    set_seed(seed)


@pytest.mark.parametrize("seed", [-1, MAX_SEED + 1, 1.5, True, "42"])
def test_bad_seeds_are_rejected(seed: object) -> None:
    with pytest.raises(ValueError, match="seed"):
        set_seed(seed)  # type: ignore[arg-type]
