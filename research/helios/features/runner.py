"""Computing features for one coin, and saying which values are real (step 071).

The runner returns two tables of the same shape:

- **values** — the feature numbers;
- **available** — True where the number may be used, False where it may not.

A value is only available when all three of these hold:

1. enough bars have been seen (the feature's declared warm-up, step 070);
2. the bars its window covers are **actually consecutive in time** — the hourly history has
   real outages (170 missing hours for BTC, including 75 hours in February 2018), and a
   "24-bar return" computed across a gap is not a 24-hour return at all;
3. the computed number is a real number, not NaN or infinity.

Where a value is unavailable it is set to NaN, never 0. Zero is a claim that nothing moved;
NaN with a mask beside it is the truth: we do not know.

Step 081's warm-up contract is positional: lookback includes the current bar, so a
lookback of w masks the first w-1 rows (or more if warmup explicitly requests it).
This is enforced even when the feature itself returns finite early values. Reaching
the warm-up boundary does not override gaps or nonfinite output. Each invocation
starts with only the history supplied to it; an input index is not prior history.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from helios.data.klines import interval_us
from helios.features.registry import REGISTRY, FeatureError, FeatureRegistry, FeatureSpec

REQUIRED_COLUMNS = ("open_time", "open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class FeatureFrame:
    """Feature values for one coin, with a mask saying which of them may be used."""

    symbol: str
    open_time: pd.Series
    values: pd.DataFrame
    available: pd.DataFrame

    @property
    def names(self) -> list[str]:
        return list(self.values.columns)

    @property
    def rows(self) -> int:
        return len(self.values)

    def usable(self) -> pd.DataFrame:
        """Only the rows where every feature is available, with the timestamp kept."""
        keep = self.available.all(axis=1)
        frame = self.values.loc[keep].copy()
        frame.insert(0, "open_time", self.open_time.loc[keep])
        return frame.reset_index(drop=True)

    def first_usable_row(self) -> int | None:
        """Position of the first row where every feature is available."""
        keep = self.available.all(axis=1).to_numpy()
        return int(keep.argmax()) if keep.any() else None

    def availability(self) -> dict[str, float]:
        """Share of rows where each feature may be used."""
        return {name: float(self.available[name].mean()) for name in self.names}


def check_bars(bars: pd.DataFrame, interval: str) -> None:
    """Refuse input that features cannot honestly be computed from."""
    missing = [column for column in REQUIRED_COLUMNS if column not in bars.columns]
    if missing:
        raise FeatureError(f"the bars are missing columns: {missing}")
    if bars.empty:
        raise FeatureError("there are no bars to compute features from")
    if not bars["open_time"].is_monotonic_increasing:
        raise FeatureError(
            "the bars must be sorted oldest first; features computed on shuffled bars would "
            "silently look into the future"
        )
    if bars["open_time"].duplicated().any():
        raise FeatureError("the bars contain duplicate timestamps")
    if (bars["open_time"] % interval_us(interval) != 0).any():
        raise FeatureError(
            f"some timestamps are not on the {interval} grid (see find_off_grid); "
            "a window measured in bars would not be a window measured in time"
        )


def _window_is_contiguous(open_time: pd.Series, lookback: int, interval: str) -> pd.Series:
    """True where the `lookback` bars ending at each row are consecutive in time."""
    if lookback <= 1:
        return pd.Series(True, index=open_time.index)
    span = (lookback - 1) * interval_us(interval)
    return (open_time - open_time.shift(lookback - 1)) == span


def _compute_one(
    spec: FeatureSpec, bars: pd.DataFrame, interval: str
) -> tuple[pd.Series, pd.Series]:
    """One feature's values and availability mask."""
    computed = spec.function(bars)
    if not isinstance(computed, pd.Series):
        computed = pd.Series(computed, index=bars.index)
    if len(computed) != len(bars):
        raise FeatureError(
            f"{spec.name}: returned {len(computed)} values for {len(bars)} bars; a feature "
            "must return one value per bar"
        )

    values = pd.Series(pd.to_numeric(computed, errors="coerce"), index=bars.index, dtype="float64")

    warm = pd.Series(np.arange(len(bars)) >= spec.warmup, index=bars.index)
    contiguous = _window_is_contiguous(bars["open_time"], spec.lookback, interval)
    finite = np.isfinite(values)

    available = warm & contiguous & finite
    return values.where(available), available


def compute_features(
    bars: pd.DataFrame,
    interval: str,
    names: list[str] | None = None,
    registry: FeatureRegistry | None = None,
    symbol: str | None = None,
) -> FeatureFrame:
    """Compute features for one coin's bars.

    `bars` must hold one coin, sorted oldest first, on the interval's grid. Pass `names` to
    compute only some features; the default is every declared feature.
    """
    target = REGISTRY if registry is None else registry
    check_bars(bars, interval)

    if symbol is None and "symbol" in bars.columns:
        found = bars["symbol"].unique()
        if len(found) > 1:
            raise FeatureError(
                f"the bars hold several coins ({sorted(found)}); compute features one coin "
                "at a time, or a window would run across two different series"
            )
        symbol = str(found[0])

    specs = target.all() if names is None else [target.get(name) for name in names]
    if not specs:
        raise FeatureError("no features are declared, so there is nothing to compute")

    values: dict[str, pd.Series] = {}
    available: dict[str, pd.Series] = {}
    for spec in specs:
        values[spec.name], available[spec.name] = _compute_one(spec, bars, interval)

    return FeatureFrame(
        symbol=symbol or "unknown",
        open_time=bars["open_time"].reset_index(drop=True),
        values=pd.DataFrame(values).reset_index(drop=True),
        available=pd.DataFrame(available).reset_index(drop=True),
    )
