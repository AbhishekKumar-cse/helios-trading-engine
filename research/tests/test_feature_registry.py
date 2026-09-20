"""Tests for declaring features (step 070).

Each test uses its **own registry**, so declarations never leak between tests or into the
project's real feature set.
"""

import pandas as pd
import pytest

from helios.features.registry import (
    FEATURE_SET_VERSION,
    REGISTRY,
    FeatureError,
    FeatureRegistry,
    FeatureSpec,
    Units,
    feature,
)


@pytest.fixture
def registry() -> FeatureRegistry:
    return FeatureRegistry()


def declare(
    registry: FeatureRegistry,
    name: str = "log_return_1h",
    lookback: int = 2,
    warmup: int | None = None,
    units: Units = Units.LOG_RETURN,
):
    @feature(name=name, lookback=lookback, warmup=warmup, units=units, registry=registry)
    def compute(bars: pd.DataFrame) -> pd.Series:
        """Return from the previous close to this one."""
        return bars["close"]

    return compute


# ---------------------------------------------------------------- declaring


def test_a_declared_feature_is_listed(registry: FeatureRegistry) -> None:
    declare(registry)
    assert registry.names() == ["log_return_1h"]
    assert "log_return_1h" in registry
    assert len(registry) == 1


def test_the_declaration_is_kept(registry: FeatureRegistry) -> None:
    declare(registry, lookback=25)
    spec = registry.get("log_return_1h")
    assert isinstance(spec, FeatureSpec)
    assert spec.lookback == 25
    assert spec.units is Units.LOG_RETURN
    assert spec.description.startswith("Return from the previous close")


def test_the_function_still_works_and_carries_its_spec(registry: FeatureRegistry) -> None:
    compute = declare(registry)
    bars = pd.DataFrame({"close": [1.0, 2.0]})
    assert compute(bars).tolist() == [1.0, 2.0]  # callable as before
    assert compute.spec.name == "log_return_1h"


def test_features_are_listed_in_name_order(registry: FeatureRegistry) -> None:
    declare(registry, name="volatility_24h")
    declare(registry, name="log_return_4h")
    declare(registry, name="trade_count_1h", units=Units.COUNT)
    assert registry.names() == ["log_return_4h", "trade_count_1h", "volatility_24h"]
    assert [spec.name for spec in registry] == registry.names()


def test_the_same_name_cannot_be_declared_twice(registry: FeatureRegistry) -> None:
    declare(registry)
    with pytest.raises(FeatureError, match="already declared"):
        declare(registry)


def test_the_refusal_mentions_the_version(registry: FeatureRegistry) -> None:
    declare(registry)
    with pytest.raises(FeatureError) as failure:
        declare(registry)
    assert "FEATURE_SET_VERSION" in str(failure.value)


# ---------------------------------------------------------------- warm-up


def test_warmup_defaults_to_one_less_than_the_lookback(registry: FeatureRegistry) -> None:
    """A value depending on 24 bars cannot exist until 23 earlier bars have been seen."""
    declare(registry, lookback=24)
    assert registry.get("log_return_1h").warmup == 23


def test_a_longer_warmup_can_be_stated(registry: FeatureRegistry) -> None:
    """Some features (an exponential average) need history to settle."""
    declare(registry, lookback=2, warmup=100)
    assert registry.get("log_return_1h").warmup == 100


def test_a_warmup_shorter_than_possible_is_refused(registry: FeatureRegistry) -> None:
    with pytest.raises(FeatureError, match="warmup must be at least 23"):
        declare(registry, lookback=24, warmup=5)


def test_a_negative_warmup_is_refused(registry: FeatureRegistry) -> None:
    with pytest.raises(FeatureError, match="warmup cannot be negative"):
        declare(registry, lookback=1, warmup=-1)


def test_a_single_bar_feature_needs_no_warmup(registry: FeatureRegistry) -> None:
    declare(registry, name="close_price", lookback=1, units=Units.PRICE)
    assert registry.get("close_price").warmup == 0


def test_the_longest_warmup_is_reported(registry: FeatureRegistry) -> None:
    """The runner skips this many bars at the start of a period."""
    declare(registry, name="log_return_1h", lookback=2)
    declare(registry, name="log_return_24h", lookback=25)
    declare(registry, name="volatility_168h", lookback=169)
    assert registry.max_warmup() == 168
    assert registry.max_warmup(["log_return_1h", "log_return_24h"]) == 24


def test_an_empty_registry_needs_no_warmup(registry: FeatureRegistry) -> None:
    assert registry.max_warmup() == 0


# ---------------------------------------------------------------- bad declarations


@pytest.mark.parametrize("bad", ["LogReturn", "1h_return", "x", "log return", "log-return"])
def test_a_bad_name_is_refused(registry: FeatureRegistry, bad: str) -> None:
    with pytest.raises(FeatureError, match="must be lower-case"):
        declare(registry, name=bad)


def test_a_lookback_below_one_is_refused(registry: FeatureRegistry) -> None:
    with pytest.raises(FeatureError, match="at least 1 bar"):
        declare(registry, lookback=0)


def test_a_feature_without_a_docstring_is_refused(registry: FeatureRegistry) -> None:
    """A feature nobody can explain is a feature nobody can review."""
    with pytest.raises(FeatureError, match="write a docstring"):

        @feature(name="mystery", lookback=1, units=Units.RATIO, registry=registry)
        def compute(bars: pd.DataFrame) -> pd.Series:
            return bars["close"]


def test_a_feature_taking_no_arguments_is_refused(registry: FeatureRegistry) -> None:
    with pytest.raises(FeatureError, match="must take the bars"):

        @feature(name="nothing_in", lookback=1, units=Units.RATIO, registry=registry)
        def compute() -> None:
            """Takes no bars, so it cannot be a feature."""


def test_an_unknown_feature_is_refused(registry: FeatureRegistry) -> None:
    declare(registry, name="log_return_4h")
    with pytest.raises(FeatureError, match="no feature named 'volatility_24h'"):
        registry.get("volatility_24h")


def test_the_error_lists_what_is_declared(registry: FeatureRegistry) -> None:
    declare(registry, name="log_return_4h")
    with pytest.raises(FeatureError) as failure:
        registry.get("missing")
    assert "declared: log_return_4h" in str(failure.value)


# ---------------------------------------------------------------- the project registry


def test_the_feature_set_has_a_version() -> None:
    assert FEATURE_SET_VERSION == "v1"


def test_the_project_registry_exists_and_is_separate(registry: FeatureRegistry) -> None:
    """Declaring into a test registry must never touch the real one."""
    before = len(REGISTRY)
    declare(registry, name="only_in_the_test")
    assert len(REGISTRY) == before
    assert "only_in_the_test" not in REGISTRY


def test_units_cover_what_features_produce() -> None:
    assert {"log_return", "fraction", "price", "volume", "count", "ratio"} <= {
        unit.value for unit in Units
    }
