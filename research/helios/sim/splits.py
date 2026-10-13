"""Chronological split evaluation with TEST authorization before loading (107)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, time, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import Connection, Engine

from helios.alpha.output import BoundedAlphaSeries
from helios.common.config import canonical_json, config_hash
from helios.common.project_config import FeesConfig, HorizonFamily, SplitsConfig, load_splits
from helios.data.klines import interval_us
from helios.registry.api import RegistryError, get_alpha
from helios.registry.experiments import require_open_experiment
from helios.registry.results import Split
from helios.registry.test_access import TestSetAccess, record_test_access
from helios.sim.costs import NetSimulation, simulate_net
from helios.sim.diagnostics import SimulationDiagnostics, simulation_diagnostics
from helios.sim.positions import SimulationError, _times
from helios.sim.validity import InvalidReason, ValidityConfig, ValidityResult, alpha_validity


@dataclass(frozen=True)
class SplitWindow:
    split: Split
    family: HorizonFamily
    start_us: int
    end_us: int  # exclusive
    interval: str
    horizon_periods: int
    splits_json: str
    splits_hash: str


@dataclass(frozen=True)
class SplitEvaluation:
    window: SplitWindow
    alpha_id: str
    version: int
    validity: ValidityResult
    diagnostics: SimulationDiagnostics | None
    simulation: NetSimulation | None
    test_access: TestSetAccess | None


def split_window(
    split: Split, *, interval: str, horizon_periods: int = 1, splits: SplitsConfig | None = None
) -> SplitWindow:
    split = Split(split)
    selected = load_splits() if splits is None else SplitsConfig.model_validate(splits.model_dump())
    family = {"1h": HorizonFamily.HOURLY, "1m": HorizonFamily.MINUTE}.get(interval)
    if family is None or family not in selected.families:
        raise SimulationError("split evaluation requires a configured hourly or minute family")
    period = interval_us(interval)
    settings = selected.families[family]
    if (
        isinstance(horizon_periods, bool)
        or not isinstance(horizon_periods, int)
        or horizon_periods < 1
    ):
        raise SimulationError("horizon_periods must be a positive integer")
    if horizon_periods * period > settings.embargo_days * 86_400_000_000:
        raise SimulationError("prediction horizon exceeds the configured embargo")
    bounds = getattr(settings, split.value)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    start = datetime.combine(bounds.start, time(), tzinfo=UTC)
    end = datetime.combine(bounds.end + timedelta(days=1), time(), tzinfo=UTC)
    return SplitWindow(
        split,
        family,
        (start - epoch) // timedelta(microseconds=1),
        (end - epoch) // timedelta(microseconds=1),
        interval,
        horizon_periods,
        canonical_json(selected),
        config_hash(selected),
    )


def _authorize(
    connection: Connection,
    window: SplitWindow,
    *,
    experiment_id: int,
    alpha_id: str,
    version: int,
    actor: str,
    purpose: str,
) -> TestSetAccess | None:
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 1
        for value in (experiment_id, version)
    ):
        raise SimulationError("experiment_id and alpha version must be positive integers")
    experiment = require_open_experiment(connection, experiment_id)
    definition = get_alpha(connection, alpha_id, version)
    if (
        definition.horizon_family != window.family
        or definition.horizon_periods != window.horizon_periods
    ):
        raise SimulationError("registered alpha horizon does not match the split window")
    if window.split is not Split.TEST:
        return None
    if experiment.snapshot_id is None:
        raise RegistryError("TEST evaluation requires a registered experiment snapshot")
    if len(actor.strip()) < 2:
        raise RegistryError("TEST evaluation requires an identified actor")
    return record_test_access(
        connection,
        alpha_id=alpha_id,
        version=version,
        snapshot_id=experiment.snapshot_id,
        actor=actor,
        purpose=purpose,
    )


def _split_inputs(
    alpha: BoundedAlphaSeries, bars: pd.DataFrame, window: SplitWindow
) -> tuple[BoundedAlphaSeries, pd.DataFrame]:
    if not isinstance(alpha, BoundedAlphaSeries):
        raise SimulationError("split evaluation requires bounded alpha")
    alpha_validity(alpha)  # validate the original indexes/types before reindexing
    if not bars.columns.is_unique or "open_time" not in bars:
        raise SimulationError("split bars require unique columns and open_time")
    times = _times(bars.open_time)
    alpha_times = _times(alpha.open_time)
    # An input loader may include earlier causal warm-up history, never later rows.
    if (times >= window.end_us).any() or (alpha_times >= window.end_us).any():
        raise SimulationError("loader returned data beyond the authorized split end")
    rows = (times >= window.start_us) & (times < window.end_us)
    selected = bars.loc[rows].copy(deep=True)
    selected_times = times[rows]
    if not np.isin(alpha_times[(alpha_times >= window.start_us)], selected_times).all():
        raise SimulationError("split alpha timestamps must belong to supplied split bars")
    # Explicitly align every bar; absent alpha is unavailable rather than silently dropped.
    values = pd.Series(alpha.values.to_numpy(), index=alpha_times).reindex(selected_times)
    available = pd.Series(alpha.available.to_numpy(), index=alpha_times).reindex(
        selected_times, fill_value=False
    )
    aligned = replace(
        alpha,
        open_time=pd.Series(selected_times),
        values=values.reset_index(drop=True),
        available=available.reset_index(drop=True),
    )
    return aligned, selected


def evaluate_split(
    engine: Engine,
    *,
    experiment_id: int,
    alpha_id: str,
    version: int,
    split: Split,
    interval: str,
    load_inputs: Callable[[SplitWindow], tuple[BoundedAlphaSeries, pd.DataFrame]],
    horizon_periods: int = 1,
    splits: SplitsConfig | None = None,
    validity_config: ValidityConfig | None = None,
    fees: FeesConfig | None = None,
    execution_lag: int = 1,
    actor: str = "",
    purpose: str = "",
) -> SplitEvaluation:
    """Reserve TEST in a committed transaction before invoking the trusted input loader.

    Failure or invalidity after loading still consumes that TEST access. No implicit
    all-splits call exists. The loader must use only the authorized window and causal
    earlier history; it must not inspect TEST when asked for TRAIN or VALID.
    """
    selected = load_splits() if splits is None else splits
    selected = SplitsConfig.model_validate(selected.model_dump())
    window = split_window(
        split, interval=interval, horizon_periods=horizon_periods, splits=selected
    )
    policy = (
        ValidityConfig()
        if validity_config is None
        else ValidityConfig.model_validate(validity_config.model_dump())
    )
    with engine.begin() as connection:
        access = _authorize(
            connection,
            window,
            experiment_id=experiment_id,
            alpha_id=alpha_id,
            version=version,
            actor=actor,
            purpose=purpose,
        )
    # The reservation transaction has committed. Do not expose data before this point.
    alpha, bars = _split_inputs(*load_inputs(window), window)
    validity = alpha_validity(alpha, config=policy)
    observed = bars.iloc[policy.warmup_rows :]
    times = _times(observed.open_time)
    reasons = list(validity.reasons)
    if len(times) > 1 and (np.diff(times) != interval_us(interval)).any():
        reasons.append(InvalidReason.DATA_GAPS)
    if "close" not in observed or not np.isfinite(observed.close.to_numpy(dtype=float)).all():
        reasons.append(InvalidReason.NON_FINITE_PRICES)
    if reasons:
        validity = replace(validity, status="INVALID", reasons=tuple(reasons))
    if not validity.valid:
        return SplitEvaluation(window, alpha_id, version, validity, None, None, access)
    offset = policy.warmup_rows
    alpha = replace(
        alpha,
        open_time=alpha.open_time.iloc[offset:].copy(),
        values=alpha.values.iloc[offset:].copy(),
        available=alpha.available.iloc[offset:].copy(),
    )
    bars = bars.iloc[offset:].copy()
    # A fresh simulation resets to flat and charges entry; no embargo-crossing P&L.
    with engine.begin() as connection:
        simulation = simulate_net(
            connection,
            experiment_id=experiment_id,
            alpha=alpha,
            bars=bars,
            interval=interval,
            execution_lag=execution_lag,
            fees=fees,
        )
    diagnostics = simulation_diagnostics(simulation, splits=selected)
    return SplitEvaluation(window, alpha_id, version, validity, diagnostics, simulation, access)
