"""Build a versioned feature store from canonical bars (step 083).

One symbol is computed over its whole history before partitioning by UTC year.
Each value has an `available__<name>` boolean beside it. Off-grid source rows are
retained with every feature unavailable; no observation or missing interval is filled.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from helios.common.config import HeliosConfig
from helios.common.lineage import RunContext
from helios.data.bars import DEFAULT_OUT_DIR as BARS_DIR
from helios.data.binance import sha256_file
from helios.data.klines import interval_us
from helios.data.loader import load_bars
from helios.data.snapshots import describe_bars
from helios.features import basic  # noqa: F401 -- populate the production registry
from helios.features.registry import FEATURE_SET_VERSION, REGISTRY, FeatureError
from helios.features.runner import compute_features

DEFAULT_FEATURE_DIR = BARS_DIR.parent / "features"
AVAILABILITY_PREFIX = "available__"


class FeatureBuildConfig(HeliosConfig):
    feature_set_version: str
    interval: str
    features: list[dict[str, str | int]]
    off_grid_policy: str = "retain_unavailable"


@dataclass(frozen=True)
class FeatureBuildResult:
    symbol: str
    interval: str
    rows: int
    off_grid_rows: int
    files_written: list[Path]
    manifest: Path


def _atomic_json(path: Path, value: dict[str, object]) -> None:
    temporary = path.with_suffix(".json.part")
    try:
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def build_features(
    symbol: str,
    interval: str,
    bars_dir: Path = BARS_DIR,
    out_dir: Path = DEFAULT_FEATURE_DIR,
) -> FeatureBuildResult:
    """Export all registered features for one coin, preserving every source row.

    Output: feature_set=v1/interval=1h/symbol=BTCUSDT/year=2025/features.parquet.
    The symbol-level manifest records source file hashes, run lineage, feature specs,
    output hashes and off-grid counts. Derived builds may be dirty and say so explicitly;
    they are not reported research results. No database connection is required.
    """
    step = interval_us(interval)
    if not re.fullmatch(r"[A-Z0-9]+", symbol):
        raise FeatureError(f"invalid symbol {symbol!r}: expected uppercase letters and digits")
    specs = REGISTRY.all()
    config = FeatureBuildConfig(
        feature_set_version=FEATURE_SET_VERSION,
        interval=interval,
        features=[
            {
                "name": s.name,
                "lookback": s.lookback,
                "warmup": s.warmup,
                "units": s.units.value,
                "description": s.description,
            }
            for s in specs
        ],
    )
    source = describe_bars([symbol], interval, bars_dir)
    context = RunContext.capture(config, source.snapshot_id, seed=0)
    bars = load_bars(symbol, interval, out_dir=bars_dir)
    on_grid = (bars["open_time"] % step) == 0
    if not on_grid.any():
        raise FeatureError(f"{symbol} {interval}: no on-grid bars to compute features from")
    computed = compute_features(bars.loc[on_grid], interval, names=[s.name for s in specs])
    values = computed.values.copy()
    masks = computed.available.copy()
    values.index = masks.index = bars.index[on_grid]
    values = values.reindex(bars.index)
    masks = masks.reindex(bars.index, fill_value=False).add_prefix(AVAILABILITY_PREFIX)
    exported = pd.concat([bars[["open_time"]], values, masks], axis=1)
    years = pd.to_datetime(bars["open_time"], unit="us", utc=True).dt.year
    root = (
        out_dir / f"feature_set={FEATURE_SET_VERSION}" / f"interval={interval}" / f"symbol={symbol}"
    )
    destinations = {root / f"year={year}" / "features.parquet" for year in years.unique()}
    stale = set(root.glob("year=*/features.parquet")) - destinations
    if stale:
        raise FeatureError(f"stale feature partitions under {root}; review them before rebuilding")
    files: list[Path] = []
    for year, group in exported.groupby(years, sort=True):
        path = root / f"year={year}" / "features.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".parquet.part")
        try:
            group.to_parquet(temporary, engine="pyarrow", compression="zstd", index=False)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        files.append(path)
    lineage = asdict(context)
    lineage["created_at"] = context.created_at.isoformat()
    manifest = root / "manifest.json"
    _atomic_json(
        manifest,
        {
            "config": config.model_dump(mode="json"),
            "lineage": lineage,
            "input_snapshot": asdict(source),
            "symbol": symbol,
            "rows": len(exported),
            "off_grid_rows": int((~on_grid).sum()),
            "availability_prefix": AVAILABILITY_PREFIX,
            "availability": {
                name: float(masks[f"{AVAILABILITY_PREFIX}{name}"].mean()) for name in computed.names
            },
            "files": [
                {"path": path.relative_to(root).as_posix(), "sha256": sha256_file(path)}
                for path in files
            ],
        },
    )
    return FeatureBuildResult(
        symbol, interval, len(exported), int((~on_grid).sum()), files, manifest
    )
