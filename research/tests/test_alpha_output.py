"""Final bounds must preserve causality/masks and never alter intermediate math."""

from datetime import date

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError
from sqlalchemy import Connection

from helios.alpha.definition import AlphaDefinition, register_alpha_definition
from helios.alpha.errors import DSLEvaluationError
from helios.alpha.evaluator import AlphaSeries
from helios.alpha.output import (
    OutputConvention,
    bound_alpha,
    evaluate_definition,
    evaluate_universe_definition,
)
from helios.common.config import config_hash
from helios.features.runner import FeatureFrame
from helios.registry.api import get_alpha


def idea(source: str = "x * 3 - 2", **changes: object) -> AlphaDefinition:
    return AlphaDefinition.model_validate(
        {
            "alpha_id": "t_bounded_alpha",
            "version": 1,
            "name": "Bounded alpha",
            "provenance": "QUANT",
            "feature_set_version": "v1",
            "horizon_family": "H-HOURLY",
            "horizon_periods": 1,
            "params": {},
            "expression": source,
            "author": "Test",
            "code_commit": "a" * 40,
            **changes,
        }
    )


def frame(symbol: str = "BTCUSDT", values: list[float] | None = None) -> FeatureFrame:
    data = [1.0, 2.0, -2.0, 0.0] if values is None else values
    index = pd.Index(range(10, 10 + len(data)))
    return FeatureFrame(
        symbol,
        pd.Series(np.arange(len(data)) * 3_600_000_000, index=index),
        pd.DataFrame({"x": data}, index=index),
        pd.DataFrame({"x": [True] * len(data)}, index=index, dtype=bool),
    )


def test_final_bounding_after_full_formula_and_metadata() -> None:
    features = frame()
    result = evaluate_definition(idea(), features)
    # Clipping x*3 before subtracting 2 would incorrectly make the first two -1.
    np.testing.assert_array_equal(result.values, [1.0, 1.0, -1.0, -1.0])
    assert result.available.all()
    assert result.output == OutputConvention()
    pd.testing.assert_series_equal(result.open_time, features.open_time)
    assert result.values.index.equals(features.values.index)
    result.values.iloc[0] = 99
    assert features.values.iloc[0, 0] == 1


def test_unavailable_and_infinite_values_do_not_saturate_to_positions() -> None:
    raw = AlphaSeries(
        "BTCUSDT",
        pd.Series(range(6)),
        pd.Series([-2.0, 0.0, 2.0, np.inf, np.nan, 0.5]),
        pd.Series([True, True, True, True, True, False]),
    )
    result = bound_alpha(raw)
    np.testing.assert_allclose(
        result.values, [-1.0, 0.0, 1.0, np.nan, np.nan, np.nan], equal_nan=True
    )
    assert result.available.tolist() == [True, True, True, False, False, False]
    assert np.isinf(raw.values.iloc[3])


def test_bounding_after_cross_sectional_mean_not_before() -> None:
    frames = {"BTCUSDT": frame(values=[2.0]), "ETHUSDT": frame("ETHUSDT", [4.0])}
    result = evaluate_universe_definition(
        idea("cs_demean(x)"),
        frames,
        listing_dates={s: date(1970, 1, 1) for s in frames},
    )
    assert result["BTCUSDT"].values.iloc[0] == -1
    assert result["ETHUSDT"].values.iloc[0] == 1


def test_prelisting_and_empty_members_stay_unavailable() -> None:
    frames = {"BTCUSDT": frame(values=[2.0]), "ETHUSDT": frame("ETHUSDT", [])}
    result = evaluate_universe_definition(
        idea("cs_rank(x) * 3"),
        frames,
        listing_dates={"BTCUSDT": date(1970, 1, 1), "ETHUSDT": date(1970, 1, 2)},
    )
    assert result["BTCUSDT"].values.iloc[0] == 1
    assert result["ETHUSDT"].rows == 0


def test_position_scale_is_stored_not_applied_twice() -> None:
    definition = idea("x", output={"position_scale": 2.0})
    result = evaluate_definition(definition, frame(values=[0.5, 3.0]))
    np.testing.assert_array_equal(result.values, [0.5, 1.0])
    assert result.output.position_scale == 2
    assert definition.to_registry().spec["output"] == definition.output.model_dump(mode="json")
    assert config_hash(definition) != config_hash(idea("x"))


@pytest.mark.parametrize("scale", [0, -1, float("nan"), float("inf"), True, "2"])
def test_invalid_position_scale_rejected(scale: object) -> None:
    with pytest.raises(ValidationError):
        idea(output={"position_scale": scale})


@pytest.mark.parametrize(
    "change",
    [
        {"lower": -2.0},
        {"upper": 2.0},
        {"upper": True},
        {"convention": "full_sample"},
    ],
)
def test_only_declared_unit_convention_allowed(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        idea(output=change)


def test_model_refs_require_separate_inference() -> None:
    definition = idea(expression=None, model_ref="example://model", provenance="ML")
    with pytest.raises(DSLEvaluationError, match="model inference"):
        evaluate_definition(definition, frame())


def test_bounding_does_not_change_earlier_outputs_when_future_changes() -> None:
    inputs = frame(values=[0.1, 0.2, 0.3, 0.4])
    definition = idea("ts_mean(x, 2) * 4")
    before = evaluate_definition(definition, inputs, interval="1h")
    inputs.values.iloc[-1, 0] = 1e100
    after = evaluate_definition(definition, inputs, interval="1h")
    pd.testing.assert_series_equal(before.values.iloc[:-1], after.values.iloc[:-1])
    assert not before.available.iloc[0] and np.isnan(before.values.iloc[0])


def test_output_convention_round_trips_through_registry(connection: Connection) -> None:
    definition = idea(output={"position_scale": 0.5})
    registered = register_alpha_definition(connection, definition)
    stored = get_alpha(connection, registered.alpha_id, registered.version)
    assert stored.spec["output"] == definition.output.model_dump(mode="json")
