"""Validity distinguishes unusable observations from performance rejection."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from helios.alpha.evaluator import AlphaSeries
from helios.sim.positions import SimulationError
from helios.sim.validity import InvalidReason, ValidityConfig, alpha_validity


def alpha(values: list[float], available: list[bool] | None = None) -> AlphaSeries:
    return AlphaSeries(
        "BTCUSDT",
        pd.Series(np.arange(len(values)) * 3_600_000_000),
        pd.Series(values, dtype=float),
        pd.Series(available if available is not None else [True] * len(values), dtype=bool),
    )


@pytest.mark.parametrize("value", [-1.0, 0.0, 1.0])
def test_constant_is_invalid_not_rejected(value: float) -> None:
    result = alpha_validity(alpha([value] * 10))
    assert result.status == "INVALID" and not result.valid
    assert result.reasons == (InvalidReason.CONSTANT_ALPHA,)


def test_explicit_warmup_is_excluded_and_not_inferred() -> None:
    source = alpha([np.nan, np.nan, -1, 0, 1], [False, False, True, True, True])
    accepted = alpha_validity(source, config=ValidityConfig(warmup_rows=2))
    assert accepted.valid and accepted.n_periods == 2
    assert accepted.n_unavailable_after_warmup == 0
    assert not alpha_validity(source).valid
    source.available.iloc[3] = False
    source.values.iloc[3] = np.nan
    assert (
        InvalidReason.UNAVAILABLE_AFTER_WARMUP
        in alpha_validity(source, config=ValidityConfig(warmup_rows=2)).reasons
    )


@pytest.mark.parametrize("value", [np.nan, np.inf, -np.inf])
def test_claimed_available_nonfinite_is_invalid(value: float) -> None:
    result = alpha_validity(alpha([-1, value, 1]))
    assert InvalidReason.NON_FINITE_ALPHA in result.reasons
    assert InvalidReason.UNAVAILABLE_AFTER_WARMUP in result.reasons


def test_minimum_counts_observed_intervals_and_records_configuration() -> None:
    source = alpha([-1, 0, 1])
    default = alpha_validity(source)
    strict = alpha_validity(source, config=ValidityConfig(min_periods=3))
    assert default.valid and strict.reasons == (InvalidReason.TOO_FEW_PERIODS,)
    assert default.config_hash != strict.config_hash and default.input_hash == strict.input_hash
    assert alpha_validity(alpha([])).reasons == (InvalidReason.TOO_FEW_PERIODS,)
    source.values.iloc[-1] = 0.5
    assert alpha_validity(source).input_hash != default.input_hash


def test_malformed_inputs_fail_and_warmup_controls_are_strict() -> None:
    source = alpha([-1, 0, 1])
    with pytest.raises(SimulationError, match="boolean"):
        alpha_validity(replace(source, available=pd.Series([1, 1, 1])))
    with pytest.raises(SimulationError, match="index"):
        alpha_validity(replace(source, values=source.values.set_axis([1, 2, 3])))
    for kwargs in ({"warmup_rows": True}, {"min_periods": 1}, {"warmup_rows": -1}):
        with pytest.raises(ValidationError):
            ValidityConfig(**kwargs)
