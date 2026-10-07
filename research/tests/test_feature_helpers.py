"""Step 080: independently calculated trailing operators and no-future-data properties."""

from collections.abc import Callable

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from helios.features.basic import rolling_zscore
from helios.features.helpers import rank_ts, zscore

Operator = Callable[[pd.Series, int], pd.Series]


def test_zscore_uses_sample_standard_deviation() -> None:
    values = zscore(pd.Series([1.0, 2.0, 3.0, 4.0, 2.0]), 4)
    assert values.iloc[:3].isna().all()
    assert values.iloc[3] == pytest.approx(1.161895003862225)
    # [2,3,4,2]: mean 2.75, sample variance 11/12.
    assert values.iloc[4] == pytest.approx(-0.75 / np.sqrt(11 / 12))


def test_constant_zscore_is_unknown_and_existing_entry_point_matches() -> None:
    x = pd.Series([5.0] * 6 + [7.0, 9.0])
    assert zscore(x, 4).iloc[:6].isna().all()
    pd.testing.assert_series_equal(zscore(x, 4), rolling_zscore(x, 4))


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([1, 2, 3, 4], 1.0),
        ([4, 3, 2, 1], 0.25),
        ([1, 3, 4, 2], 0.5),
        ([1, 2, 4, 2], 0.625),
        ([2, 2, 2, 2], 0.625),
    ],
)
def test_rank_order_and_average_ties(values: list[int], expected: float) -> None:
    result = rank_ts(pd.Series(values), 4)
    assert result.iloc[:3].isna().all()
    assert result.iloc[3] == expected


def test_rank_drops_observations_outside_window() -> None:
    # The old 100 no longer counts when ranking 3 within [1,2,3].
    assert rank_ts(pd.Series([100, 1, 2, 3]), 3).iloc[-1] == 1.0


def test_rank_window_one_and_numpy_integer_window() -> None:
    x = pd.Series([2.0, np.nan, -5.0])
    result = rank_ts(x, np.int64(1))
    assert result.iloc[0] == result.iloc[2] == 1.0
    assert pd.isna(result.iloc[1])


@pytest.mark.parametrize("operator", [zscore, rank_ts])
@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf, "bad"])
def test_invalid_observation_masks_window_until_it_leaves(operator: Operator, bad: object) -> None:
    x = pd.Series([1, 2, 3, bad, 4, 5, 6], dtype=object)
    result = operator(x, 3)
    assert np.isfinite(result.iloc[2])
    assert result.iloc[3:6].isna().all()
    assert np.isfinite(result.iloc[6])


@pytest.mark.parametrize("operator", [zscore, rank_ts])
@pytest.mark.parametrize("window", [0, -1, 1.5, True, "3"])
def test_invalid_window_is_refused(operator: Operator, window: object) -> None:
    with pytest.raises(ValueError, match="window"):
        operator(pd.Series([1, 2, 3]), window)  # type: ignore[arg-type]


def test_sample_zscore_requires_two_observations() -> None:
    with pytest.raises(ValueError, match="at least 2"):
        zscore(pd.Series([1]), 1)


@pytest.mark.parametrize("operator", [zscore, rank_ts])
def test_empty_short_input_and_index_preservation(operator: Operator) -> None:
    empty = operator(pd.Series([], dtype="float64"), 3)
    assert empty.empty and empty.dtype == np.dtype("float64")
    assert operator(pd.Series([1, 2]), 3).isna().all()
    x = pd.Series(["1", "2", "3", "4"], index=pd.Index([10, 20, 30, 40], name="bar"))
    original = x.copy(deep=True)
    result = operator(x, 3)
    pd.testing.assert_index_equal(result.index, x.index)
    assert result.dtype == np.dtype("float64")
    assert result.iloc[:2].isna().all()
    assert np.isfinite(result.iloc[2:]).all()
    pd.testing.assert_series_equal(x, original)


@pytest.mark.parametrize("operator", [zscore, rank_ts])
@given(
    values=st.lists(st.integers(-100, 100), min_size=2, max_size=50),
    window=st.integers(2, 10),
    cut=st.integers(0, 49),
)
def test_future_perturbation_and_truncation_cannot_change_past(
    operator: Operator, values: list[int], window: int, cut: int
) -> None:
    x = pd.Series(values, dtype="float64")
    cut %= len(x)
    before = operator(x, window).iloc[: cut + 1]
    changed = x.copy()
    changed.iloc[cut + 1 :] = 1_000_000.0
    pd.testing.assert_series_equal(before, operator(changed, window).iloc[: cut + 1])
    pd.testing.assert_series_equal(before, operator(x.iloc[: cut + 1], window))
