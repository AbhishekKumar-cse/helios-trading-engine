"""Random seeds (step 029).

`set_seed(seed)` fixes Python's `random` module and numpy's global random generator, so
the same seed always produces the same random numbers (reproducible runs). It also
returns a fresh `numpy.random.Generator`, which new code should prefer over the global
generator because it can be passed around explicitly.

The same seed is stored in `RunContext.seed` (step 028), so every result records it.
"""

from __future__ import annotations

import random

import numpy as np

MAX_SEED = 2**32 - 1  # numpy's legacy global generator only accepts 0 .. 2**32 - 1


def set_seed(seed: int) -> np.random.Generator:
    """Seed `random` and numpy's global generator; return a numpy Generator from `seed`."""
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= MAX_SEED:
        raise ValueError(f"seed must be an integer between 0 and {MAX_SEED}, got {seed!r}")
    random.seed(seed)
    np.random.seed(seed)  # legacy global generator, still used by some libraries
    return np.random.default_rng(seed)
