"""Hourly feature-at-t / forward-return datasets with explicit availability (114)."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self

import duckdb
import numpy as np
import numpy.typing as npt
import pandas as pd
from pydantic import Field, StrictInt, model_validator

from helios.alpha.evaluator import _check_frame
from helios.common.config import HeliosConfig, canonical_json, config_hash
from helios.data.klines import interval_us
from helios.data.loader import TimeLike, to_micros
from helios.features.runner import FeatureFrame
from helios.features.store import AVAILABILITY_PREFIX, DEFAULT_FEATURE_DIR
from helios.sim.positions import _times

HOUR_US = 3_600_000_000


class DatasetError(ValueError):
    """Malformed feature/price inputs or dataset configuration."""


class DatasetConfig(HeliosConfig):
    interval: Literal["1h", "1m"] = "1h"
    features: tuple[str, ...] = Field(min_length=1)
    feature_set_version: str = Field(default="v1", pattern=r"^[a-zA-Z0-9_-]+$")
    horizon: StrictInt = Field(default=1, ge=1, lt=2**63 // HOUR_US)
    label: Literal["close_t_plus_h_over_close_t_minus_one_v1"] = (
        "close_t_plus_h_over_close_t_minus_one_v1"
    )

    @model_validator(mode="after")
    def _names(self) -> Self:
        if len(set(self.features)) != len(self.features) or any(
            not re.fullmatch(r"[a-z][a-z0-9_]*", f) for f in self.features
        ):
            raise ValueError("features must be unique safe feature-column names")
        return self


@dataclass(frozen=True)
class Sample:
    symbol: str
    open_time: int
    label_end_time: int
    features: tuple[float, ...]
    target: float


@dataclass(frozen=True)
class AvailabilityCounts:
    symbol: str
    n_rows: int
    n_feature_unavailable: int
    n_label_unavailable: int
    n_usable: int


@dataclass(frozen=True)
class HourlyDataset:
    config: DatasetConfig
    config_json: str
    config_hash: str
    snapshot_id: str | None
    input_hashes: tuple[tuple[str, str], ...]
    counts: tuple[AvailabilityCounts, ...]
    samples: tuple[Sample, ...]

    @property
    def X(self) -> npt.NDArray[np.float64]:
        """Independent NumPy materialization; mutations cannot alter source evidence."""
        return np.asarray([s.features for s in self.samples], dtype=np.float64).reshape(
            -1, len(self.config.features)
        )

    @property
    def y(self) -> npt.NDArray[np.float64]:
        return np.asarray([s.target for s in self.samples], dtype=np.float64)


def _numeric(column: pd.Series) -> npt.NDArray[np.float64]:
    if (
        not pd.api.types.is_numeric_dtype(column.dtype)
        or pd.api.types.is_bool_dtype(column.dtype)
        or pd.api.types.is_complex_dtype(column.dtype)
    ):
        raise DatasetError("dataset values must be real numeric columns")
    return np.asarray(column.to_numpy(na_value=np.nan, copy=True), dtype=np.float64)


def load_feature_frame(
    symbol: str,
    start: TimeLike,
    end: TimeLike,
    *,
    config: DatasetConfig,
    feature_dir: Path = DEFAULT_FEATURE_DIR,
) -> FeatureFrame:
    """Read an explicit range of the existing feature store, without imputation.

    This low-level loader does not grant TEST permission. Its caller must supply
    authorized dates; the guarded split builder is added in step 115.
    """
    selected = DatasetConfig.model_validate(config.model_dump())
    if not re.fullmatch(r"[A-Z0-9]+", symbol):
        raise DatasetError("symbol must be uppercase letters/digits")
    first, last = to_micros(start), to_micros(end, end=True)
    if first is None or last is None or first > last:
        raise DatasetError("feature loading requires ordered explicit bounds")
    root = (
        feature_dir
        / f"feature_set={selected.feature_set_version}"
        / f"interval={selected.interval}"
        / f"symbol={symbol}"
    )
    columns = [
        "open_time",
        *selected.features,
        *(AVAILABILITY_PREFIX + f for f in selected.features),
    ]
    projection = ", ".join('"' + name + '"' for name in columns)
    with duckdb.connect() as connection:
        frame = connection.execute(
            f"SELECT {projection} FROM read_parquet($path, hive_partitioning=true) "
            "WHERE open_time >= $first AND open_time <= $last "
            "AND CAST(year AS BIGINT) BETWEEN $first_year AND $last_year ORDER BY open_time",
            {
                "path": str(root / "year=*" / "features.parquet"),
                "first": first,
                "last": last,
                "first_year": pd.Timestamp(first, unit="us").year,
                "last_year": pd.Timestamp(last, unit="us").year,
            },
        ).df()
    return FeatureFrame(
        symbol,
        frame.open_time.copy(),
        frame[list(selected.features)].copy(),
        frame[[AVAILABILITY_PREFIX + f for f in selected.features]].rename(
            columns={AVAILABILITY_PREFIX + f: f for f in selected.features}
        ),
    )


def build_dataset(
    features: Mapping[str, FeatureFrame],
    bars: Mapping[str, pd.DataFrame],
    *,
    config: DatasetConfig,
    snapshot_id: str | None = None,
) -> HourlyDataset:
    """Align exact timestamps; retain only complete X/y pairs and count exclusions.

    Does not fit scaling, shuffle rows, register results, or authorize TEST access.
    Features must be causal outputs of the existing feature pipeline.
    """
    selected = DatasetConfig.model_validate(config.model_dump())
    period = interval_us(selected.interval)
    if not features or set(features) != set(bars):
        raise DatasetError("features and bars require the same nonempty symbol universe")
    samples, counts, hashes = [], [], []
    for symbol in sorted(features):
        fv, prices = features[symbol], bars[symbol]
        _check_frame(fv)
        if fv.symbol != symbol or ("symbol" in prices and not prices.symbol.eq(symbol).all()):
            raise DatasetError("dataset symbol mismatch")
        if not prices.columns.is_unique or not {"open_time", "close"}.issubset(prices):
            raise DatasetError("bars require unique timestamp and close columns")
        times, ftimes = _times(prices.open_time), _times(fv.open_time)
        if (times % period != 0).any() or (ftimes % period != 0).any():
            raise DatasetError(
                "dataset timestamps must lie on the configured hourly/minute UTC grid"
            )
        if not np.isin(ftimes, times).all():
            raise DatasetError("feature timestamps must belong to supplied bars")
        close = _numeric(prices.close)
        if (np.isfinite(close) & (close <= 0)).any():
            raise DatasetError("finite close prices must be positive")
        columns, masks, source_arrays = [], [], [times, close, ftimes]
        for name in selected.features:
            if name not in fv.values:
                raise DatasetError(f"missing feature {name}")
            raw = _numeric(fv.values[name])
            availability = fv.available[name]
            if availability.dtype != bool or availability.isna().any():
                raise DatasetError("feature availability must be boolean")
            mask = availability.to_numpy(dtype=bool, copy=True)
            if (mask & ~np.isfinite(raw)).any():
                raise DatasetError("available features must be finite")
            values = pd.Series(np.where(mask, raw, np.nan), index=ftimes).reindex(times).to_numpy()
            columns.append(values)
            masks.append(np.isfinite(values))
            source_arrays.extend([raw, mask])
        matrix = np.column_stack(columns)
        usable_features = np.logical_and.reduce(masks)
        labels = np.full(len(times), np.nan)
        label_end = np.zeros(len(times), dtype=np.int64)
        h = selected.horizon
        if h < len(times):
            contiguous = np.asarray(
                [int(b) - int(a) == h * period for a, b in zip(times[:-h], times[h:], strict=True)]
            )
            known = contiguous & np.isfinite(close[:-h]) & np.isfinite(close[h:])
            with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
                forward = close[h:] / close[:-h] - 1
            labels[:-h] = np.where(known & np.isfinite(forward), forward, np.nan)
            label_end[:-h] = times[h:]
        usable_labels = np.isfinite(labels)
        paired = usable_features & usable_labels
        for i in np.flatnonzero(paired):
            samples.append(
                Sample(
                    symbol,
                    int(times[i]),
                    int(label_end[i]),
                    tuple(float(v) for v in matrix[i]),
                    float(labels[i]),
                )
            )
        counts.append(
            AvailabilityCounts(
                symbol,
                len(times),
                int((~usable_features).sum()),
                int((~usable_labels).sum()),
                int(paired.sum()),
            )
        )
        digest = hashlib.sha256(symbol.encode())
        for array in source_arrays:
            kind = "u1" if array.dtype.kind == "b" else "<i8" if array.dtype.kind in "iu" else "<f8"
            digest.update(len(array).to_bytes(8, "little"))
            digest.update(array.astype(kind).tobytes())
        hashes.append((symbol, digest.hexdigest()))
    samples.sort(key=lambda sample: (sample.open_time, sample.symbol))
    return HourlyDataset(
        selected,
        canonical_json(selected),
        config_hash(selected),
        snapshot_id,
        tuple(hashes),
        tuple(counts),
        tuple(samples),
    )
