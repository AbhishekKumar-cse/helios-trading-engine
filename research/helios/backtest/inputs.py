"""Authorized TRAIN/VALID source adapters; synthetic inputs remain explicitly labelled."""

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from helios.alpha.definition import AlphaDefinition, AlphaProvenance
from helios.alpha.output import evaluate_definition
from helios.backtest.config import BacktestConfig
from helios.common.config import config_hash
from helios.common.lineage import RunContext
from helios.common.project_config import HorizonFamily
from helios.common.types import AlphaStatus, AlphaValue, Bar, DecisionLineage
from helios.data.binance import sha256_file
from helios.data.replay import HistoricalBarSource
from helios.data.snapshots import load_manifest
from helios.features import basic  # noqa: F401
from helios.features.registry import REGISTRY
from helios.features.store import DEFAULT_FEATURE_DIR
from helios.ml.dataset import HOUR_US, DatasetConfig, load_feature_frame
from helios.ml.registered_alpha import frozen_ml_series
from helios.registry.api import AlphaDefinition as StoredDefinition
from helios.registry.api import Provenance
from helios.sim.splits import split_window


@dataclass(frozen=True)
class ReplayInputs:
    bars: tuple[Bar, ...]
    signals: tuple[AlphaValue, ...]
    sha256: str


def load_inputs(
    config: BacktestConfig, definition: StoredDefinition, context: RunContext
) -> ReplayInputs:
    lineage = DecisionLineage(
        alpha_id=config.alpha_id,
        alpha_version=config.alpha_version,
        feature_set_version=definition.feature_set_version,
        horizon_family=HorizonFamily.HOURLY,
        code_commit=context.code_commit,
        config_hash=config_hash(config),
        snapshot_id=config.snapshot_id,
        seed=config.seed,
    )
    if config.data_kind == "synthetic_csv":
        assert config.csv_path is not None
        path = Path(config.csv_path)
        if (
            sha256_file(path) != config.csv_sha256
            or definition.spec.get("synthetic_csv_sha256") != config.csv_sha256
        ):
            raise ValueError("synthetic source/definition checksum mismatch")
        with path.open() as handle:
            rows = list(csv.DictReader(handle))
        if [int(row["bar"]) for row in rows] != list(range(len(rows))):
            raise ValueError("synthetic CSV bars must have consecutive explicit indices")
        from decimal import Decimal

        bars = tuple(
            Bar(
                symbol=config.symbol,
                source="synthetic_correctness_fixture",
                sequence=i,
                open_time=config.start_us + i * HOUR_US,
                ingest_time=config.start_us + (i + 1) * HOUR_US,
                interval="1h",
                snapshot_id=config.snapshot_id,
                **{key: Decimal(row[key]) for key in ("open", "high", "low", "close", "volume")},
            )
            for i, row in enumerate(rows)
        )
        signals = tuple(
            AlphaValue(
                symbol=config.symbol,
                timestamp=bar.ingest_time,
                lineage=lineage,
                status=AlphaStatus.OK if row["decision_alpha"] else AlphaStatus.UNAVAILABLE,
                value=float(row["decision_alpha"]) if row["decision_alpha"] else None,
            )
            for bar, row in zip(bars, rows, strict=True)
        )
    else:
        bars = tuple(
            HistoricalBarSource(
                (config.symbol,),
                config.start_us,
                config.end_us - 1,
                snapshot_id=config.snapshot_id,
                strict_gaps=True,
            ).events()
        )
        alpha_definition = AlphaDefinition(
            alpha_id=definition.alpha_id,
            version=definition.version,
            name=definition.name,
            provenance=AlphaProvenance.ML
            if definition.provenance is Provenance.ML
            else AlphaProvenance.QUANT,
            feature_set_version=definition.feature_set_version,
            horizon_family=definition.horizon_family,
            horizon_periods=definition.horizon_periods,
            author=definition.author,
            code_commit=definition.code_commit,
            **{
                k: v
                for k, v in definition.spec.items()
                if k in ("expression", "model_ref", "params", "output")
            },
        )
        if alpha_definition.expression is None:
            alpha, evidence = frozen_ml_series(
                alpha_definition,
                split_window(
                    config.split, interval="1h", horizon_periods=definition.horizon_periods
                ),
                symbol=config.symbol,
                snapshot_id=config.snapshot_id,
            )
            lineage = DecisionLineage.model_validate(
                lineage.model_dump()
                | dict(
                    code_commit=evidence["transform_lineage"]["code_commit"],
                    config_hash=evidence["policy_hash"],
                    model_hash=evidence["model_sha256"],
                )
            )
        else:
            root = (
                DEFAULT_FEATURE_DIR
                / f"feature_set={definition.feature_set_version}"
                / "interval=1h"
                / f"symbol={config.symbol}"
            )
            manifest = json.loads((root / "manifest.json").read_text())
            snapshot = load_manifest(config.snapshot_id)
            registered = {file.path: file.sha256 for file in snapshot.files}
            if any(
                registered.get(f["path"]) != f["sha256"]
                for f in manifest["input_snapshot"]["files"]
            ):
                raise ValueError("feature provenance differs from the registered bar snapshot")
            for file in manifest["files"]:
                path = (root / file["path"]).resolve()
                if not path.is_relative_to(root.resolve()) or sha256_file(path) != file["sha256"]:
                    raise ValueError("feature-store checksum mismatch")
            features = load_feature_frame(
                config.symbol,
                config.start_us,
                config.end_us - 1,
                config=DatasetConfig(
                    features=tuple(REGISTRY.names()),
                    feature_set_version=definition.feature_set_version,
                ),
            )
            alpha = evaluate_definition(alpha_definition, features, interval="1h")
        lookup = {
            int(t): (bool(a), v)
            for t, a, v in zip(alpha.open_time, alpha.available, alpha.values, strict=True)
        }
        signals = tuple(
            AlphaValue(
                symbol=config.symbol,
                timestamp=bar.ingest_time,
                lineage=lineage,
                status=AlphaStatus.OK
                if lookup.get(bar.open_time, (False, None))[0]
                else AlphaStatus.UNAVAILABLE,
                value=float(lookup[bar.open_time][1])
                if lookup.get(bar.open_time, (False, None))[0]
                else None,
            )
            for bar in bars
        )
    if (
        not bars
        or bars[0].open_time != config.start_us
        or bars[-1].close_time != config.end_us
        or any(bar.ingest_time > config.end_us for bar in bars)
    ):
        raise ValueError("backtest requires complete observed coverage of the configured range")
    encoded = json.dumps(
        dict(
            bars=[b.model_dump(mode="json") for b in bars],
            signals=[s.model_dump(mode="json") for s in signals],
        ),
        sort_keys=True,
    ).encode()
    return ReplayInputs(bars, signals, hashlib.sha256(encoded).hexdigest())
