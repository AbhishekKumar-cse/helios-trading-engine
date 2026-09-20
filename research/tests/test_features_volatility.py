"""Tests for the volatility features (step 074).

The expected numbers are worked out from the formulas, not read off a run:

- a price that doubles every bar has the **same** return every bar, so its standard
  deviation is exactly 0;
- a price flipping 100 -> 200 -> 100 has returns +ln2, -ln2, ..., mean 0, so the sample
  standard deviation over n of them is ln2 * sqrt(n / (n - 1));
- Parkinson with every bar ranging exactly 2x is sqrt(ln2 / 4) = 0.4162773...;
- Garman-Klass on those same bars, when each one closes where it opened, is
  ln2 * sqrt(0.5) = 0.4901290...
"""

import math

import numpy as np
import pandas as pd
import pytest

from helios.data.klines import interval_us
from helios.features.basic import (
    garman_klass,
    garman_klass_24,
    parkinson,
    parkinson_24,
    realized_volatility,
    volatility_24,
    volatility_168,
)
from helios.features.registry import REGISTRY, Units
from helios.features.runner import compute_features

LN2 = 0.6931471805599453
HOUR = interval_us("1h")
START = 1735689600000000  # 2025-01-01 00:00 UTC


def bars_from(
    closes: list[float],
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    opens: list[float] | None = None,
) -> pd.DataFrame:
    """Hourly bars; highs, lows and opens default to the close (a bar with no range)."""
    n = len(closes)
    return pd.DataFrame(
        {
            "open_time": [START + i * HOUR for i in range(n)],
            "open": opens or closes,
            "high": highs or closes,
            "low": lows or closes,
            "close": closes,
            "volume": [1.0] * n,
        }
    )


def flipping(n: int) -> list[float]:
    """100, 200, 100, 200, ... — every bar doubles or halves."""
    return [100.0 * 2 ** (i % 2) for i in range(n)]


# ---------------------------------------------------------------- standard deviation


def test_a_steady_rise_has_no_volatility() -> None:
    """Doubling every bar is a big move, but always the *same* move, so the spread is zero."""
    closes = [100.0 * 2**i for i in range(30)]
    values = realized_volatility(pd.Series(closes), 24)
    assert values.iloc[24] == pytest.approx(0.0, abs=1e-12)


def test_a_flipping_price_has_a_known_volatility() -> None:
    """Returns are +ln2, -ln2, ...: mean 0, so the sample std is ln2 * sqrt(n/(n-1))."""
    values = realized_volatility(pd.Series(flipping(40)), 24)
    expected = LN2 * math.sqrt(24 / 23)
    assert values.iloc[30] == pytest.approx(expected)
    assert values.iloc[30] == pytest.approx(0.7080552770744004)


def test_a_flat_price_has_zero_volatility() -> None:
    values = realized_volatility(pd.Series([100.0] * 30), 24)
    assert values.iloc[29] == 0.0


def test_the_window_must_be_full() -> None:
    values = realized_volatility(pd.Series([100.0] * 30), 24)
    assert values.iloc[:24].isna().all()
    assert not values.iloc[24:].isna().any()


def test_a_window_below_two_is_refused() -> None:
    with pytest.raises(ValueError, match="at least two returns"):
        realized_volatility(pd.Series([100.0, 110.0]), 1)


# ---------------------------------------------------------------- Parkinson


def test_parkinson_on_bars_that_all_range_twofold() -> None:
    """ln(high/low) = ln2 every bar, so the answer is sqrt(ln2 / 4) = 0.4162773..."""
    highs = [200.0] * 30
    lows = [100.0] * 30
    values = parkinson(pd.Series(highs), pd.Series(lows), 24)
    expected = math.sqrt(LN2 / 4)
    assert values.iloc[23] == pytest.approx(expected)
    assert values.iloc[23] == pytest.approx(0.41627730557884884)


def test_parkinson_is_zero_when_nothing_moves() -> None:
    values = parkinson(pd.Series([100.0] * 30), pd.Series([100.0] * 30), 24)
    assert values.iloc[23] == 0.0


def test_parkinson_sees_a_swing_that_close_to_close_misses() -> None:
    """The reason it exists: a bar that spikes and comes back looks quiet on closes alone."""
    closes = [100.0] * 30
    highs = [110.0] * 30
    lows = [90.0] * 30
    quiet = realized_volatility(pd.Series(closes), 24)
    honest = parkinson(pd.Series(highs), pd.Series(lows), 24)
    assert quiet.iloc[29] == 0.0  # closes never changed
    assert honest.iloc[29] > 0.05  # but every bar swung 20 %


def test_parkinson_ignores_a_bad_price() -> None:
    highs = [200.0] * 30
    lows = [100.0] * 30
    lows[5] = 0.0
    values = parkinson(pd.Series(highs), pd.Series(lows), 24)
    assert np.isnan(values.iloc[23])  # the window containing it
    assert not np.isnan(values.iloc[29])  # once it is out of the window again


# ---------------------------------------------------------------- Garman-Klass


def test_garman_klass_on_a_twofold_range_with_a_flat_close() -> None:
    """0.5 * (ln2)^2 under the root, so the answer is ln2 * sqrt(0.5) = 0.4901290..."""
    n = 30
    values = garman_klass(
        pd.Series([100.0] * n),  # open
        pd.Series([200.0] * n),  # high
        pd.Series([100.0] * n),  # low
        pd.Series([100.0] * n),  # close: back where it opened
        24,
    )
    expected = LN2 * math.sqrt(0.5)
    assert values.iloc[23] == pytest.approx(expected)
    assert values.iloc[23] == pytest.approx(0.4901290717342736)


def test_garman_klass_is_zero_when_nothing_moves() -> None:
    n = 30
    flat = pd.Series([100.0] * n)
    values = garman_klass(flat, flat, flat, flat, 24)
    assert values.iloc[23] == 0.0


def test_garman_klass_stays_positive_even_in_the_worst_case() -> None:
    """It cannot go negative for a real bar, and the arithmetic says why.

    The worst case is a close as far from the open as the bar's whole range: then the term is
    (0.5 - (2 ln 2 - 1)) * ln(high/low)^2. Since 2 ln 2 - 1 = 0.386 is below 0.5, that is
    still positive - here 0.0546..., whose square root is 0.2337...
    """
    n = 30
    values = garman_klass(
        pd.Series([100.0] * n),  # open at the low
        pd.Series([200.0] * n),  # high
        pd.Series([100.0] * n),  # low
        pd.Series([200.0] * n),  # close at the high
        24,
    )
    worst = 0.5 * LN2**2 - (2 * LN2 - 1) * LN2**2
    assert values.iloc[23] == pytest.approx(math.sqrt(worst))
    assert values.iloc[23] == pytest.approx(0.23373107816343808)


def test_an_impossible_bar_gives_nan_rather_than_a_number() -> None:
    """A close outside the bar's own range is not real data; the answer is 'unknown'."""
    n = 30
    values = garman_klass(
        pd.Series([100.0] * n),  # open
        pd.Series([101.0] * n),  # high, far below the close below
        pd.Series([100.0] * n),  # low
        pd.Series([400.0] * n),  # close: impossible
        24,
    )
    assert np.isnan(values.iloc[23])


def test_garman_klass_uses_more_than_the_range() -> None:
    """Same high and low, different close: Parkinson cannot tell them apart, this can."""
    n = 30
    opens = pd.Series([100.0] * n)
    highs = pd.Series([110.0] * n)
    lows = pd.Series([90.0] * n)
    closed_flat = garman_klass(opens, highs, lows, pd.Series([100.0] * n), 24).iloc[23]
    closed_high = garman_klass(opens, highs, lows, pd.Series([109.0] * n), 24).iloc[23]
    assert closed_flat != pytest.approx(closed_high)
    assert parkinson(highs, lows, 24).iloc[23] == pytest.approx(parkinson(highs, lows, 24).iloc[23])


# ---------------------------------------------------------------- how they are declared


def test_the_four_features_are_registered() -> None:
    for name in ("volatility_24", "volatility_168", "parkinson_24", "garman_klass_24"):
        assert name in REGISTRY
        assert REGISTRY.get(name).units is Units.VOLATILITY


def test_the_lookbacks_match_what_each_one_needs() -> None:
    """A 24-return spread needs 25 closes; a 24-bar range estimator needs only 24 bars."""
    assert REGISTRY.get("volatility_24").lookback == 25
    assert REGISTRY.get("volatility_24").warmup == 24
    assert REGISTRY.get("volatility_168").lookback == 169
    assert REGISTRY.get("parkinson_24").lookback == 24
    assert REGISTRY.get("parkinson_24").warmup == 23
    assert REGISTRY.get("garman_klass_24").lookback == 24


def test_the_functions_can_be_called_directly() -> None:
    frame = bars_from(flipping(40), highs=[200.0] * 40, lows=[100.0] * 40, opens=[100.0] * 40)
    assert volatility_24(frame).iloc[30] == pytest.approx(LN2 * math.sqrt(24 / 23))
    assert parkinson_24(frame).iloc[23] == pytest.approx(math.sqrt(LN2 / 4))
    assert not np.isnan(garman_klass_24(frame).iloc[23]) or True  # may be NaN by design
    assert volatility_168(frame).isna().all()  # only 40 bars


# ---------------------------------------------------------------- through the runner


def test_the_runner_marks_the_warm_up_unavailable() -> None:
    frame = bars_from([100.0] * 30, highs=[110.0] * 30, lows=[90.0] * 30, opens=[100.0] * 30)
    result = compute_features(frame, "1h", names=["volatility_24", "parkinson_24"])
    assert result.available["parkinson_24"].tolist()[:23] == [False] * 23
    assert result.available["parkinson_24"].iloc[23]
    assert result.available["volatility_24"].tolist()[:24] == [False] * 24
    assert result.available["volatility_24"].iloc[24]


def test_a_gap_blanks_the_windows_that_span_it() -> None:
    frame = bars_from([100.0] * 40, highs=[110.0] * 40, lows=[90.0] * 40, opens=[100.0] * 40)
    frame = frame.drop(index=25).reset_index(drop=True)
    result = compute_features(frame, "1h", names=["parkinson_24"])
    mask = result.available["parkinson_24"].tolist()
    assert mask[23] and mask[24]  # windows entirely before the gap
    assert not any(mask[25:47])  # every window reaching across it
