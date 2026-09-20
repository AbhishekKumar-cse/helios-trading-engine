"""Declaring features, and what each one needs to be computed (step 070).

A feature is a number computed from past bars — a return, a moving average, a measure of
volatility. Every feature here declares three things beyond its code:

| Declared | Why it must be declared |
|---|---|
| `lookback` | how many bars the value depends on, **including the current one** |
| `warmup` | how many bars at the start cannot produce a value |
| `units` | what the number means, so two features are never added together by mistake |

Why not just compute and see: at the start of any period the first few values are undefined.
If they quietly come out as zero, an alpha reads "no movement" where the truth is "unknown",
and a backtest starts trading on numbers that never existed. Declaring the warm-up lets the
runner (step 071) mark those bars UNAVAILABLE instead.

`FEATURE_SET_VERSION` is recorded with every alpha definition. When a feature's meaning
changes, the version changes, and older results keep pointing at the set they were computed
with.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from enum import StrEnum
from inspect import signature
from typing import Any

FEATURE_SET_VERSION = "v1"

FEATURE_NAME = re.compile(r"^[a-z][a-z0-9_]{2,63}$")

FeatureFunction = Callable[..., Any]


class FeatureError(Exception):
    """Raised when a feature is declared wrongly or asked for and not found."""


class Units(StrEnum):
    """What a feature's number means.

    Keeping this explicit prevents the classic mistake of combining a price with a return, or
    comparing a percentage against a fraction.
    """

    LOG_RETURN = "log_return"  # natural logarithm of a price ratio
    FRACTION = "fraction"  # 0.25 means 25 %
    PRICE = "price"  # quote currency, e.g. USDT
    VOLUME = "volume"  # base currency, e.g. BTC
    COUNT = "count"  # a number of things (trades, bars)
    RATIO = "ratio"  # one quantity divided by another of the same kind
    VOLATILITY = "volatility"  # a standard deviation of log returns, per bar
    ZSCORE = "zscore"  # standard deviations from a mean
    SECONDS = "seconds"


@dataclass(frozen=True)
class FeatureSpec:
    """Everything known about one feature."""

    name: str
    lookback: int
    warmup: int
    units: Units
    description: str
    function: FeatureFunction

    def __post_init__(self) -> None:
        if not FEATURE_NAME.match(self.name):
            raise FeatureError(
                f"feature name {self.name!r} must be lower-case letters, digits and "
                "underscores (3-64 characters), e.g. 'log_return_24h'"
            )
        if self.lookback < 1:
            raise FeatureError(
                f"{self.name}: lookback must be at least 1 bar (the current one), "
                f"got {self.lookback}"
            )
        if self.warmup < 0:
            raise FeatureError(f"{self.name}: warmup cannot be negative, got {self.warmup}")
        # a warm-up longer than the lookback is fine (some features need history to settle);
        # a shorter one is not, because the value could not exist yet
        if self.warmup < self.lookback - 1:
            raise FeatureError(
                f"{self.name}: a feature looking back {self.lookback} bars cannot produce a "
                f"value before bar {self.lookback - 1}, so warmup must be at least "
                f"{self.lookback - 1}, got {self.warmup}"
            )
        if not self.description.strip():
            raise FeatureError(f"{self.name}: write a docstring saying what this feature is")


class FeatureRegistry:
    """The set of declared features, keyed by name."""

    def __init__(self) -> None:
        self._features: dict[str, FeatureSpec] = {}

    def add(self, spec: FeatureSpec) -> FeatureSpec:
        if spec.name in self._features:
            raise FeatureError(
                f"feature {spec.name!r} is already declared; pick another name, or change the "
                "existing one and raise FEATURE_SET_VERSION"
            )
        self._features[spec.name] = spec
        return spec

    def get(self, name: str) -> FeatureSpec:
        try:
            return self._features[name]
        except KeyError:
            known = ", ".join(self.names()) or "none"
            raise FeatureError(f"no feature named {name!r}; declared: {known}") from None

    def names(self) -> list[str]:
        """Every declared feature name, in alphabetical order."""
        return sorted(self._features)

    def all(self) -> list[FeatureSpec]:
        """Every declared feature, in name order."""
        return [self._features[name] for name in self.names()]

    def max_warmup(self, names: list[str] | None = None) -> int:
        """The longest warm-up among these features: how many bars to skip at the start."""
        wanted = self.all() if names is None else [self.get(name) for name in names]
        return max((spec.warmup for spec in wanted), default=0)

    def __contains__(self, name: object) -> bool:
        return name in self._features

    def __len__(self) -> int:
        return len(self._features)

    def __iter__(self) -> Iterator[FeatureSpec]:
        return iter(self.all())


REGISTRY = FeatureRegistry()
"""The project's feature set. `helios.features.basic` and friends add to it on import."""


def feature(
    name: str,
    *,
    lookback: int,
    units: Units,
    warmup: int | None = None,
    registry: FeatureRegistry | None = None,
) -> Callable[[FeatureFunction], FeatureFunction]:
    """Declare a function as a feature.

    `warmup` defaults to `lookback - 1`: a value that depends on 24 bars cannot exist until
    23 earlier bars have been seen. Features that need longer (an exponential average, say)
    state a larger number themselves.

    The function is returned unchanged, so it can still be called directly, and carries its
    declaration as `.spec`.
    """

    def decorate(function: FeatureFunction) -> FeatureFunction:
        parameters = signature(function).parameters
        if not parameters:
            raise FeatureError(f"{name}: a feature function must take the bars as its argument")

        spec = FeatureSpec(
            name=name,
            lookback=lookback,
            warmup=lookback - 1 if warmup is None else warmup,
            units=units,
            description=(function.__doc__ or "").strip(),
            function=function,
        )
        # `registry or REGISTRY` would be wrong: an empty registry is falsy because this
        # class defines __len__, so a fresh registry would silently fall back to the global one
        target = REGISTRY if registry is None else registry
        target.add(spec)
        function.spec = spec  # type: ignore[attr-defined]
        return function

    return decorate
