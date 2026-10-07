"""Trailing time-series operators for features and the future alpha DSL (step 080).

Windows count observations, include the current value and never look ahead. Callers
must supply chronological data for one instrument. These Series-only helpers cannot
detect missing time intervals: declared feature lookbacks and the feature runner handle
timestamp-gap masking. Neither operator fills missing observations.
"""

from numbers import Integral

import numpy as np
import pandas as pd


def _window(w: int, minimum: int) -> int:
    if isinstance(w, bool) or not isinstance(w, Integral) or w < minimum:
        raise ValueError(
            f"window needs at least {minimum} values and must be an integer, got {w!r}"
        )
    return int(w)


def _numbers(x: pd.Series) -> pd.Series:
    numbers = pd.to_numeric(x, errors="coerce").astype("float64")
    return numbers.where(np.isfinite(numbers))


def zscore(x: pd.Series, w: int) -> pd.Series:
    """(x - trailing mean) / trailing sample standard deviation (ddof=1).

    Requires w >= 2 and w finite observations. Warm-up, missing/invalid values,
    and zero-variance windows yield NaN. For [1, 2, 3, 4] with w=4, the last
    score is 1.5 / sqrt(5/3), approximately 1.161895.
    """
    window = _window(w, 2)
    numbers = _numbers(x)
    rolling = numbers.rolling(window, min_periods=window, center=False)
    spread = rolling.std(ddof=1)
    result = (numbers - rolling.mean()) / spread.where(spread > 0)
    return pd.Series(result, index=x.index, dtype="float64")


def rank_ts(x: pd.Series, w: int) -> pd.Series:
    """Current value's ascending percentile rank in its trailing w observations.

    Rank is one-based with average ranks for ties, divided by w (range 1/w to 1).
    For [1, 2, 2, 4], the last 2's rank in [1, 2, 2] is 2.5/3 with w=3.
    A constant window ranks (w+1)/(2*w), not NaN: ordering ties is well defined.
    w=1 returns 1 for a finite value. Warm-up and windows with any missing,
    nonnumeric or infinite observation yield NaN until a full valid window returns.
    """
    window = _window(w, 1)
    result = (
        _numbers(x)
        .rolling(window, min_periods=window, center=False)
        .rank(method="average", ascending=True, pct=True)
    )
    return pd.Series(result, index=x.index, dtype="float64")
