"""Random seeds (step 029).

`set_seed(seed)` fixes Python's `random` module, numpy's global random generator **and
PyTorch** when it is installed, so the same seed always produces the same random numbers
(reproducible runs). It also returns a fresh `numpy.random.Generator`, which new code should
prefer over the global generator because it can be passed around explicitly.

PyTorch matters here because a network starts from random weights: without seeding it, two
runs with the same recorded seed would build different models, and the recorded seed would
be a promise the project could not keep.

The same seed is stored in `RunContext.seed` (step 028), so every result records it.
"""

from __future__ import annotations

import random

import numpy as np

MAX_SEED = 2**32 - 1  # numpy's legacy global generator only accepts 0 .. 2**32 - 1


def _seed_torch(seed: int) -> bool:
    """Seed PyTorch if it is installed. Returns whether it was."""
    try:
        import torch
    except ImportError:
        return False
    torch.manual_seed(seed)
    if torch.cuda.is_available():  # pragma: no cover - no GPU on the team's laptops
        torch.cuda.manual_seed_all(seed)
    return True


def set_seed(seed: int) -> np.random.Generator:
    """Seed `random`, numpy and PyTorch; return a numpy Generator made from `seed`."""
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= MAX_SEED:
        raise ValueError(f"seed must be an integer between 0 and {MAX_SEED}, got {seed!r}")
    random.seed(seed)
    np.random.seed(seed)  # legacy global generator, still used by some libraries
    _seed_torch(seed)
    return np.random.default_rng(seed)
