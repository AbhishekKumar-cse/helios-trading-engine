"""Calendar-month net stability and ex-ante, earlier-calibrated volatility terciles."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from math import fsum, isfinite
from typing import Literal

import numpy as np
import numpy.typing as npt
import pandas as pd

from helios.alpha.errors import DSLEvaluationError
from helios.alpha.evaluator import _check_frame
from helios.common.config import HeliosConfig, canonical_json, config_hash
from helios.common.project_config import SplitsConfig
from helios.features.runner import FeatureFrame
from helios.sim.costs import NetSimulation
from helios.sim.diagnostics import DAY_US, _real
from helios.sim.metrics import ReturnMetrics, SimulationMetrics, return_metrics, simulation_metrics
from helios.sim.positions import Mask, SimulationError, Values, _times


class StabilityConfig(HeliosConfig):
    interval: Literal["1h", "1m"] = "1h"
    volatility_feature: str = "volatility_24"
    quantile_method: Literal["linear"] = "linear"
    subperiod: Literal["utc_calendar_month"] = "utc_calendar_month"
    regime_time: Literal["previous_bar_close_v1"] = "previous_bar_close_v1"
    positive_denominator: Literal["defined_monthly_sharpes_v1"] = "defined_monthly_sharpes_v1"
    ties: Literal["low_le_q1_middle_le_q2_v1"] = "low_le_q1_middle_le_q2_v1"


@dataclass(frozen=True)
class VolatilityRegimeFit:
    symbol: str
    config: StabilityConfig
    config_json: str
    config_hash: str
    calibration_start_us: int
    calibration_end_us: int
    n_rows: int
    n_available: int
    lower_cut: float
    upper_cut: float
    input_hash: str


@dataclass(frozen=True)
class MonthStability:
    month: str
    metrics: ReturnMetrics
    expected_periods: int
    has_gaps: bool


@dataclass(frozen=True)
class RegimeMetrics:
    name: Literal["low", "middle", "high"]
    n_periods: int
    metrics: ReturnMetrics | None


@dataclass(frozen=True)
class StabilityResult:
    base: SimulationMetrics
    regime_fit: VolatilityRegimeFit
    evaluation_volatility_hash: str
    months: tuple[MonthStability, ...]
    n_defined_months: int
    mean_monthly_sharpe: float | None
    min_monthly_sharpe: float | None
    positive_month_fraction: float | None
    regimes: tuple[RegimeMetrics, ...]
    n_unavailable_regime: int


def _digest(
    symbol: str, name: str, times: npt.NDArray[np.int64], values: Values, mask: Mask
) -> str:
    digest = hashlib.sha256((symbol + "\0" + name + "\0").encode())
    for array in (times.astype("<i8"), values.astype("<f8"), mask.astype("u1")):
        digest.update(len(array).to_bytes(8, "little"))
        digest.update(array.tobytes())
    return digest.hexdigest()


def _volatility(
    features: FeatureFrame, config: StabilityConfig
) -> tuple[npt.NDArray[np.int64], Values, Mask]:
    try:
        _check_frame(features)
    except DSLEvaluationError as exc:
        raise SimulationError(str(exc)) from exc
    name = config.volatility_feature
    if name not in features.values:
        raise SimulationError("configured volatility feature is missing")
    column, available = features.values[name], features.available[name]
    if available.dtype != bool or available.isna().any():
        raise SimulationError("volatility availability must be boolean")
    mask = available.to_numpy(copy=True)
    _real(column.loc[available])
    if (column.loc[available] < 0).any():
        raise SimulationError("available volatility must be non-negative")
    if (
        not pd.api.types.is_numeric_dtype(column.dtype)
        or pd.api.types.is_bool_dtype(column.dtype)
        or pd.api.types.is_complex_dtype(column.dtype)
    ):
        raise SimulationError("volatility must be real numeric values")
    values = np.asarray(column.to_numpy(na_value=np.nan, copy=True), dtype=np.float64)
    times = _times(features.open_time)
    period = 3_600_000_000 if config.interval == "1h" else 60_000_000
    if (times % period != 0).any():
        raise SimulationError("volatility timestamps must lie on the configured UTC grid")
    return times, values, mask


def fit_volatility_regimes(
    features: FeatureFrame,
    *,
    calibration_start_us: int,
    calibration_end_us: int,
    config: StabilityConfig | None = None,
) -> VolatilityRegimeFit:
    """Fit only the explicit half-open earlier window; never refit on evaluation P&L."""
    if (
        isinstance(calibration_start_us, bool)
        or isinstance(calibration_end_us, bool)
        or not isinstance(calibration_start_us, int)
        or not isinstance(calibration_end_us, int)
        or calibration_start_us >= calibration_end_us
    ):
        raise SimulationError("calibration requires ordered integer UTC microsecond bounds")
    selected = (
        StabilityConfig() if config is None else StabilityConfig.model_validate(config.model_dump())
    )
    times, values, mask = _volatility(features, selected)
    selected_rows = (times >= calibration_start_us) & (times < calibration_end_us)
    eligible = selected_rows & mask
    observed = values[eligible]
    if len(observed) < 3 or len(np.unique(observed)) < 3:
        raise SimulationError(
            "terciles require at least three distinct available calibration values"
        )
    lower, upper = np.quantile(observed, [1 / 3, 2 / 3], method="linear")
    if not isfinite(float(lower)) or not isfinite(float(upper)) or lower >= upper:
        raise SimulationError("calibration has degenerate volatility terciles")
    return VolatilityRegimeFit(
        features.symbol,
        selected,
        canonical_json(selected),
        config_hash(selected),
        calibration_start_us,
        calibration_end_us,
        int(selected_rows.sum()),
        int(eligible.sum()),
        float(lower),
        float(upper),
        _digest(
            features.symbol,
            selected.volatility_feature,
            times[selected_rows],
            values[selected_rows],
            mask[selected_rows],
        ),
    )


def stability_report(
    simulation: NetSimulation,
    features: FeatureFrame,
    regime_fit: VolatilityRegimeFit,
    *,
    splits: SplitsConfig | None = None,
) -> StabilityResult:
    base = simulation_metrics(simulation, splits=splits)
    frame = simulation.table.copy(deep=True)
    config = regime_fit.config
    if (
        features.symbol != base.symbol
        or regime_fit.symbol != base.symbol
        or config.interval != simulation.gross.config.interval
    ):
        raise SimulationError("regime symbol/interval must match the simulation")
    if regime_fit.config_json != canonical_json(config) or regime_fit.config_hash != config_hash(
        config
    ):
        raise SimulationError("regime config lineage mismatch")
    if regime_fit.calibration_end_us > int(frame.open_time.iloc[0]):
        raise SimulationError("regime calibration must end before the evaluation boundary")
    if not (
        isfinite(regime_fit.lower_cut)
        and isfinite(regime_fit.upper_cut)
        and 0 <= regime_fit.lower_cut < regime_fit.upper_cut
    ):
        raise SimulationError("invalid fitted regime thresholds")
    times, volatility, mask = _volatility(features, config)
    observed_times = _times(frame.open_time.iloc[1:])
    returns = _real(frame.net_return.iloc[1:])
    if len(returns):
        returns[0] += float(frame.net_return.iloc[0])
    period = 3_600_000_000 if config.interval == "1h" else 60_000_000
    # For interval ending at t, only the feature available at close[t-1] is used.
    aligned = pd.Series(np.where(mask, volatility, np.nan), index=times).reindex(
        observed_times - period
    )
    vol = aligned.to_numpy(dtype=np.float64)
    available = np.isfinite(vol)
    months = np.asarray(
        pd.to_datetime(observed_times, unit="us", utc=True).strftime("%Y-%m"), dtype=np.str_
    )
    monthly = []
    ppy = base.config.periods_per_year
    for month in sorted(set(months)):
        metrics = return_metrics(returns[months == month], periods_per_year=ppy)
        expected = pd.Timestamp(month + "-01").days_in_month * (DAY_US // period)
        monthly.append(MonthStability(month, metrics, expected, metrics.n_periods != expected))
    sharpes = [m.metrics.annual_sharpe for m in monthly if m.metrics.annual_sharpe is not None]
    try:
        mean = fsum(sharpes) / len(sharpes) if sharpes else None
    except OverflowError as exc:
        raise SimulationError("monthly Sharpe summary overflow") from exc
    positive = sum(v > 0 for v in sharpes) / len(sharpes) if sharpes else None
    regimes = []
    bins: tuple[tuple[Literal["low", "middle", "high"], Mask], ...] = (
        ("low", available & (vol <= regime_fit.lower_cut)),
        ("middle", available & (vol > regime_fit.lower_cut) & (vol <= regime_fit.upper_cut)),
        ("high", available & (vol > regime_fit.upper_cut)),
    )
    for name, chosen in bins:
        count = int(chosen.sum())
        regimes.append(
            RegimeMetrics(
                name,
                count,
                return_metrics(returns[chosen], periods_per_year=ppy) if count else None,
            )
        )
    return StabilityResult(
        base,
        regime_fit,
        _digest(features.symbol, config.volatility_feature, times, volatility, mask),
        tuple(monthly),
        len(sharpes),
        mean,
        min(sharpes) if sharpes else None,
        positive,
        tuple(regimes),
        int((~available).sum()),
    )
