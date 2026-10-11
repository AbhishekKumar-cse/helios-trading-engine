"""Forward alignment, masked universes, ranks, monthly purging and IC-IR."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from helios.alpha.evaluator import AlphaSeries
from helios.sim.ic import ICConfig, correlation, information_coefficients
from helios.sim.positions import SimulationError

HOUR = 3_600_000_000


def pair(
    symbol: str, signal: list[float], prices: list[float], times: list[int] | None = None
) -> tuple[AlphaSeries, pd.DataFrame]:
    stamps = list(np.arange(len(prices)) * HOUR) if times is None else times
    return (
        AlphaSeries(
            symbol,
            pd.Series(stamps),
            pd.Series(signal, dtype=float),
            pd.Series(True, index=range(len(signal))),
        ),
        pd.DataFrame({"open_time": stamps, "close": prices}),
    )


@pytest.mark.parametrize("method", ["pearson", "spearman"])
def test_forward_alignment_perfect_and_inverse_signals(method: str) -> None:
    outcomes = [-0.03, -0.01, 0.01, 0.03]
    prices = [100.0]
    for value in outcomes:
        prices.append(prices[-1] * (1 + value))
    alpha, bars = pair("BTCUSDT", outcomes + [0], prices)
    result = information_coefficients(
        {alpha.symbol: alpha}, {alpha.symbol: bars}, config=ICConfig(method=method)
    )
    assert result.coins[0].overall == pytest.approx(1)
    assert result.coins[0].n_pairs == 4 and result.coins[0].n_unavailable == 1
    assert result.cross_mean is None and "five" in str(result.cross_unavailable_reason)
    inverse = replace(alpha, values=-alpha.values)
    assert information_coefficients(
        {alpha.symbol: inverse}, {alpha.symbol: bars}, config=ICConfig(method=method)
    ).coins[0].overall == pytest.approx(-1)


def test_rank_ties_and_constant_values() -> None:
    assert correlation(
        np.array([1.0, 1.0, 2.0, 3.0]), np.arange(4, dtype=float), method="spearman"
    ) == pytest.approx(0.9486832980505138)
    assert correlation(np.ones(4), np.arange(4, dtype=float), method="pearson") is None
    assert correlation(np.array([1.0]), np.array([2.0]), method="pearson") is None
    with pytest.raises(SimulationError):
        correlation(np.array([np.nan]), np.array([2.0]), method="pearson")


def test_five_coin_cross_section_requires_same_time_available_pairs() -> None:
    signals, bars = {}, {}
    for i in range(5):
        symbol = f"COIN{i}"
        signals[symbol], bars[symbol] = pair(
            symbol, [float(i), 0], [100.0, 100.0 * (1 + (i - 2) / 100)]
        )
    result = information_coefficients(signals, bars, snapshot_id="caller-snapshot")
    assert result.cross_mean == pytest.approx(1)
    assert result.cross_sectional[0].symbols == tuple(sorted(signals))
    assert result.cross_sectional[1].value is None
    assert result.snapshot_id == "caller-snapshot" and len(result.input_hashes) == 5
    assert result.cross_ic_ir is None
    signals["COIN0"].available.iloc[0] = False
    missing = information_coefficients(signals, bars)
    assert missing.cross_mean is None and len(missing.cross_sectional[0].symbols) == 4
    assert missing.input_hashes != result.input_hashes


def test_signal_row_indices_do_not_control_timestamp_alignment() -> None:
    alpha, bars = pair("BTCUSDT", [0.01, -0.01, 0], [100.0, 101.0, 99.99])
    alpha = replace(
        alpha,
        open_time=alpha.open_time.set_axis([7, 5, 9]),
        values=alpha.values.set_axis([7, 5, 9]),
        available=alpha.available.set_axis([7, 5, 9]),
    )
    assert information_coefficients({alpha.symbol: alpha}, {alpha.symbol: bars}).coins[
        0
    ].overall == pytest.approx(1)


def test_gap_horizon_tail_and_unavailable_signal_are_counted() -> None:
    alpha, bars = pair(
        "BTCUSDT", [1, 2, 3, 4], [100.0, 101.0, 102.0, 103.0], [0, HOUR, 3 * HOUR, 4 * HOUR]
    )
    alpha.available.iloc[0] = False
    result = information_coefficients({alpha.symbol: alpha}, {alpha.symbol: bars})
    assert result.coins[0].n_pairs == 1 and result.coins[0].n_unavailable == 3
    assert result.coins[0].overall is None
    long = information_coefficients(
        {alpha.symbol: alpha}, {alpha.symbol: bars}, config=ICConfig(horizon=2)
    )
    assert long.coins[0].n_pairs == 0


def test_month_boundary_purging_and_two_subperiod_ic_ir() -> None:
    start = int(pd.Timestamp("2026-01-31T22:00:00Z").value // 1000)
    times = [start + i * HOUR for i in range(7)]
    outcomes = [-0.03, 0.01, -0.02, 0.03, 0.01, -0.01]
    prices = [100.0]
    for outcome in outcomes:
        prices.append(prices[-1] * (1 + outcome))
    alpha, bars = pair("BTCUSDT", outcomes + [0], prices, times)
    result = information_coefficients({alpha.symbol: alpha}, {alpha.symbol: bars})
    assert [m.n_pairs for m in result.coins[0].months] == [1, 4]
    assert result.coins[0].months[0].value is None  # crossing label at Jan 31 23:00 purged
    assert result.coins[0].ic_ir is None
    # Four January observations give two valid January pairs; February signals inverse.
    start -= 2 * HOUR
    outcomes = [-0.03, -0.01, 0.02, 0.01, -0.02, 0.03, 0.01, -0.01]
    prices = [100.0]
    for outcome in outcomes:
        prices.append(prices[-1] * (1 + outcome))
    signal = outcomes[:4] + [-v for v in outcomes[4:]] + [0]
    alpha, bars = pair("BTCUSDT", signal, prices, [start + i * HOUR for i in range(9)])
    report = information_coefficients({alpha.symbol: alpha}, {alpha.symbol: bars}).coins[0]
    assert report.mean_monthly_ic == pytest.approx(0, abs=1e-14)
    assert report.ic_ir == pytest.approx(0, abs=1e-14)


@pytest.mark.parametrize(
    "change",
    ["duplicate", "off_grid", "nonfinite_signal", "zero_price", "text_price", "wrong_symbol"],
)
def test_bad_ic_inputs_fail(change: str) -> None:
    alpha, bars = pair("BTCUSDT", [1, 2, 3], [100.0, 101.0, 102.0])
    if change == "duplicate":
        bars.loc[1, "open_time"] = 0
    elif change == "off_grid":
        bars["open_time"] += 1
    elif change == "nonfinite_signal":
        alpha.values.iloc[0] = np.inf
    elif change == "zero_price":
        bars.loc[1, "close"] = 0
    elif change == "text_price":
        bars["close"] = "100"
    else:
        alpha = replace(alpha, symbol="OTHER")
    with pytest.raises(SimulationError):
        information_coefficients({"BTCUSDT": alpha}, {"BTCUSDT": bars})


def test_config_validation_and_future_perturbation_do_not_change_earlier_labels() -> None:
    with pytest.raises(ValidationError):
        ICConfig(horizon=True)
    alpha, bars = pair("BTCUSDT", [1, -1, 1, -1, 0], [100.0, 101.0, 99.0, 102.0, 100.0])
    # Keep early signals fixed; perturb a future price beyond their label windows.
    prefix = replace(
        alpha,
        open_time=alpha.open_time.iloc[:3],
        values=alpha.values.iloc[:3],
        available=alpha.available.iloc[:3],
    )
    first = information_coefficients({alpha.symbol: prefix}, {alpha.symbol: bars})
    bars.loc[4, "close"] = 10000
    second = information_coefficients({alpha.symbol: prefix}, {alpha.symbol: bars})
    assert first.coins == second.coins and first.cross_sectional == second.cross_sectional
    assert first.input_hashes != second.input_hashes  # actual changed source is still recorded
