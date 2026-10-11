"""Causal signal/forward-label alignment and explicitly masked predictive diagnostics."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

import numpy as np
import numpy.typing as npt
import pandas as pd
from pydantic import Field, StrictInt

from helios.alpha.evaluator import AlphaSeries
from helios.common.config import HeliosConfig, canonical_json, config_hash
from helios.sim.metrics import return_metrics
from helios.sim.positions import SimulationError, Values, _times


class ICConfig(HeliosConfig):
    interval: Literal["1h", "1m"] = "1h"
    horizon: StrictInt = Field(default=1, ge=1)
    method: Literal["spearman", "pearson"] = "spearman"
    subperiod: Literal["utc_calendar_month"] = "utc_calendar_month"
    min_cross_section: Literal[5] = 5
    label: Literal["close_t_plus_h_over_close_t_minus_one_v1"] = (
        "close_t_plus_h_over_close_t_minus_one_v1"
    )
    month_boundary: Literal["purge_crossing_labels_v1"] = "purge_crossing_labels_v1"


@dataclass(frozen=True)
class ICPeriod:
    month: str
    n_pairs: int
    value: float | None


@dataclass(frozen=True)
class CoinIC:
    symbol: str
    n_rows: int
    n_pairs: int
    n_unavailable: int
    overall: float | None
    months: tuple[ICPeriod, ...]
    mean_monthly_ic: float | None
    ic_ir: float | None


@dataclass(frozen=True)
class CrossIC:
    open_time: int
    symbols: tuple[str, ...]
    value: float | None


@dataclass(frozen=True)
class ICResult:
    config_json: str
    config_hash: str
    input_hashes: tuple[tuple[str, str], ...]
    snapshot_id: str | None
    coins: tuple[CoinIC, ...]
    cross_sectional: tuple[CrossIC, ...]
    cross_months: tuple[ICPeriod, ...]
    cross_mean: float | None
    cross_ic_ir: float | None
    cross_unavailable_reason: str | None


def correlation(x: Values, y: Values, *, method: Literal["spearman", "pearson"]) -> float | None:
    if x.ndim != 1 or y.shape != x.shape or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise SimulationError("IC requires aligned finite vectors")
    if method not in {"spearman", "pearson"}:
        raise SimulationError("unsupported IC correlation method")
    if len(x) < 2 or (x == x[0]).all() or (y == y[0]).all():
        return None
    if method == "spearman":
        x = np.asarray(pd.Series(x).rank(method="average").to_numpy(), dtype=np.float64)
        y = np.asarray(pd.Series(y).rank(method="average").to_numpy(), dtype=np.float64)
    x, y = x / np.max(np.abs(x)), y / np.max(np.abs(y))
    x, y = x - x.mean(), y - y.mean()
    norm_x, norm_y = float(np.linalg.norm(x)), float(np.linalg.norm(y))
    if norm_x == 0 or norm_y == 0:
        return None
    value = float(np.dot(x / norm_x, y / norm_y))
    if not np.isfinite(value):
        raise SimulationError("IC arithmetic overflow")
    return float(np.clip(value, -1, 1))


def _summary(values: list[float]) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    result = return_metrics(values, periods_per_year=1)
    return result.mean_return, result.per_period_sharpe


def _months(times: npt.NDArray[np.int64]) -> npt.NDArray[np.str_]:
    return np.asarray(pd.to_datetime(times, unit="us", utc=True).strftime("%Y-%m"), dtype=np.str_)


def _numeric(column: pd.Series) -> Values:
    if (
        not pd.api.types.is_numeric_dtype(column.dtype)
        or pd.api.types.is_bool_dtype(column.dtype)
        or pd.api.types.is_complex_dtype(column.dtype)
    ):
        raise SimulationError("IC signals and prices must be real numeric values")
    return column.to_numpy(dtype=float, na_value=np.nan, copy=True)


def information_coefficients(
    alphas: Mapping[str, AlphaSeries],
    bars: Mapping[str, pd.DataFrame],
    *,
    config: ICConfig | None = None,
    snapshot_id: str | None = None,
) -> ICResult:
    """TS IC per coin and same-decision-time CS IC on >=5 known instrument pairs.

    Forward labels are diagnostic outcomes, not available trading features. Label
    windows spanning missing intervals are unavailable; monthly IC purges crossing
    endpoints. Callers must supply only authorized split data, never prejoined TEST.
    """
    selected = ICConfig() if config is None else ICConfig.model_validate(config.model_dump())
    if not alphas or set(alphas) != set(bars):
        raise SimulationError("IC requires matching non-empty declared signal/bar universes")
    period = 3_600_000_000 if selected.interval == "1h" else 60_000_000
    panels: dict[str, pd.DataFrame] = {}
    coins, hashes = [], []
    for symbol in sorted(alphas):
        alpha, frame = alphas[symbol], bars[symbol]
        if alpha.symbol != symbol or frame.empty or not frame.columns.is_unique:
            raise SimulationError("IC symbol/frame mismatch")
        if not {"open_time", "close"}.issubset(frame.columns):
            raise SimulationError("IC bars require open_time and close")
        if "symbol" in frame and not frame.symbol.eq(symbol).all():
            raise SimulationError("IC bars contain another symbol")
        times, signal_times = _times(frame.open_time), _times(alpha.open_time)
        if (times % period != 0).any() or (signal_times % period != 0).any():
            raise SimulationError("IC timestamps must lie on the declared UTC grid")
        if not np.isin(signal_times, times).all():
            raise SimulationError("IC signal timestamps must belong to the supplied bars")
        if (
            not alpha.values.index.is_unique
            or not alpha.open_time.index.equals(alpha.values.index)
            or not alpha.values.index.equals(alpha.available.index)
        ):
            raise SimulationError("IC signal columns must share their index")
        if alpha.available.dtype != bool or alpha.available.isna().any():
            raise SimulationError("IC signal availability must be boolean")
        signal = _numeric(alpha.values)
        mask = alpha.available.to_numpy(copy=True)
        if (mask & ~np.isfinite(signal)).any():
            raise SimulationError("available IC signals must be finite")
        prices = _numeric(frame.close)
        if (np.isfinite(prices) & (prices <= 0)).any():
            raise SimulationError("finite IC close prices must be positive")
        aligned = pd.Series(np.where(mask, signal, np.nan), index=signal_times).reindex(times)
        x = np.asarray(aligned.to_numpy(), dtype=np.float64)
        labels: Values = np.full(len(times), np.nan, dtype=np.float64)
        future = np.zeros(len(times), dtype=np.int64)
        h = selected.horizon
        if h < len(times):
            contiguous = np.array(
                [int(b) - int(a) == h * period for a, b in zip(times[:-h], times[h:], strict=True)]
            )
            endpoints = np.isfinite(prices[:-h]) & np.isfinite(prices[h:]) & contiguous
            with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
                values = prices[h:] / prices[:-h] - 1
            labels[:-h] = np.where(endpoints & np.isfinite(values), values, np.nan)
            future[:-h] = times[h:]
        paired = np.isfinite(x) & np.isfinite(labels)
        months, future_months = _months(times), _months(future)
        reports = []
        for month in sorted(set(months)):
            usable = paired & (months == month) & (future_months == month)
            reports.append(
                ICPeriod(
                    month,
                    int(usable.sum()),
                    correlation(x[usable], labels[usable], method=selected.method),
                )
            )
        mean, ir = _summary([r.value for r in reports if r.value is not None])
        coins.append(
            CoinIC(
                symbol,
                len(times),
                int(paired.sum()),
                int((~paired).sum()),
                correlation(x[paired], labels[paired], method=selected.method),
                tuple(reports),
                mean,
                ir,
            )
        )
        panels[symbol] = pd.DataFrame({"signal": x, "label": labels, "paired": paired}, index=times)
        digest = hashlib.sha256()
        digest.update(symbol.encode())
        for array in (
            times.astype("<i8"),
            prices.astype("<f8"),
            signal_times.astype("<i8"),
            signal.astype("<f8"),
            mask.astype("u1"),
        ):
            digest.update(len(array).to_bytes(8, "little"))
            digest.update(array.tobytes())
        hashes.append((symbol, digest.hexdigest()))
    all_times = sorted(set().union(*(set(panel.index) for panel in panels.values())))
    points = []
    for time in all_times:
        symbols = tuple(
            s for s in sorted(panels) if time in panels[s].index and panels[s].at[time, "paired"]
        )
        value = None
        if len(symbols) >= selected.min_cross_section:
            value = correlation(
                np.array([panels[s].at[time, "signal"] for s in symbols]),
                np.array([panels[s].at[time, "label"] for s in symbols]),
                method=selected.method,
            )
        points.append(CrossIC(int(time), symbols, value))
    cross_months = []
    point_months = _months(np.array(all_times, dtype=np.int64))
    point_future_months = _months(
        np.array(
            [p.open_time if p.value is None else p.open_time + h * period for p in points],
            dtype=np.int64,
        )
    )
    grouped: dict[str, list[float]] = {month: [] for month in point_months}
    for point, month, future_month in zip(points, point_months, point_future_months, strict=True):
        if point.value is not None and month == future_month:
            grouped[month].append(point.value)
    for month, valid in sorted(grouped.items()):
        mean, _ = _summary(valid)
        cross_months.append(ICPeriod(month, len(valid), mean))
    cross_mean, _ = _summary([p.value for p in points if p.value is not None])
    _, cross_ir = _summary([m.value for m in cross_months if m.value is not None])
    reason = (
        None
        if cross_mean is not None
        else (
            "fewer than five declared instruments"
            if len(alphas) < 5
            else "no non-constant cross-section with five available pairs"
        )
    )
    return ICResult(
        canonical_json(selected),
        config_hash(selected),
        tuple(hashes),
        snapshot_id,
        tuple(coins),
        tuple(points),
        tuple(cross_months),
        cross_mean,
        cross_ir,
        reason,
    )
