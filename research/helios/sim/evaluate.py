"""Registered alpha -> split simulation -> immutable evidence and result (116)."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, is_dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, Field, StrictInt
from sqlalchemy import Engine, text

from helios.alpha.definition import AlphaDefinition, AlphaProvenance
from helios.alpha.output import BoundedAlphaSeries, evaluate_definition
from helios.common.config import HeliosConfig, config_hash
from helios.common.db import get_engine
from helios.common.lineage import RunContext
from helios.common.project_config import HorizonFamily, load_fees, load_gates, load_splits
from helios.data.bars import DEFAULT_OUT_DIR
from helios.data.binance import sha256_file
from helios.data.klines import interval_us
from helios.data.loader import load_bars, to_micros
from helios.data.snapshots import load_manifest
from helios.features import basic  # noqa: F401
from helios.features.registry import REGISTRY
from helios.features.runner import FeatureFrame
from helios.features.store import DEFAULT_FEATURE_DIR
from helios.ml.dataset import DatasetConfig, load_feature_frame
from helios.ml.registered_alpha import frozen_ml_series
from helios.registry.api import Provenance, RegistryError, get_alpha
from helios.registry.experiments import require_open_experiment
from helios.registry.gates import get_gate_config
from helios.registry.results import AlphaResult, Split, Status, record_result
from helios.sim.cost_sensitivity import cost_sensitivity
from helios.sim.fitness import fitness_result
from helios.sim.gates import evaluate_gates
from helios.sim.ic import ICConfig, information_coefficients
from helios.sim.splits import SplitWindow, evaluate_split
from helios.sim.stability import StabilityConfig, fit_volatility_regimes, stability_report
from helios.sim.validity import ValidityConfig

REPORT_DIR = Path(__file__).resolve().parents[3] / "reports_out" / "evaluations"


class EvaluationConfig(HeliosConfig):
    interval: Literal["1h", "1m"] = "1h"
    symbol: str = Field(default="BTCUSDT", pattern=r"^[A-Z0-9]+$")
    version: StrictInt = Field(default=1, ge=1)
    warmup_rows: StrictInt = Field(default=168, ge=0)
    min_periods: StrictInt = Field(default=2, ge=2)
    seed: StrictInt = Field(default=0, ge=0, le=2**32 - 1)
    mode: Literal["BACKTEST"] = "BACKTEST"


@dataclass(frozen=True)
class EvaluationInputs:
    features: FeatureFrame
    bars: pd.DataFrame
    calibration: FeatureFrame
    calibration_start_us: int
    calibration_end_us: int


InputLoader = Callable[[SplitWindow, AlphaDefinition], EvaluationInputs]


def _encode(value: object) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"unsupported evidence type {type(value).__name__}")


def _definition(connection: Any, alpha_id: str, version: int) -> AlphaDefinition:
    stored = get_alpha(connection, alpha_id, version)
    return AlphaDefinition.model_validate(
        {
            "alpha_id": stored.alpha_id,
            "version": stored.version,
            "name": stored.name,
            "provenance": AlphaProvenance.QUANT
            if stored.provenance is Provenance.HUMAN
            else AlphaProvenance.ML,
            "feature_set_version": stored.feature_set_version,
            "horizon_family": stored.horizon_family,
            "horizon_periods": stored.horizon_periods,
            "author": stored.author,
            "code_commit": stored.code_commit,
            **{
                key: value
                for key, value in stored.spec.items()
                if key in ("expression", "model_ref", "params", "output")
            },
        }
    )


def stored_inputs(
    window: SplitWindow, definition: AlphaDefinition, *, symbol: str
) -> EvaluationInputs:
    config = DatasetConfig(
        interval=window.interval,
        features=tuple(REGISTRY.names()),
        feature_set_version=definition.feature_set_version,
    )
    # Existing causal feature store already includes prior history; no refitting.
    features = load_feature_frame(symbol, window.start_us, window.end_us - 1, config=config)
    bars = load_bars(symbol, window.interval, window.start_us, window.end_us - 1)
    family = load_splits().families[window.family]
    start, end = (
        ("2017-12-01", "2017-12-31")
        if window.split is Split.TRAIN
        else (family.train.start, family.train.end)
    )
    calibration = load_feature_frame(symbol, start, end, config=config)
    on_grid = calibration.open_time % interval_us(window.interval) == 0
    calibration = replace(
        calibration,
        open_time=calibration.open_time.loc[on_grid].copy(),
        values=calibration.values.loc[on_grid].copy(),
        available=calibration.available.loc[on_grid].copy(),
    )
    first, last = to_micros(start), to_micros(end, end=True)
    assert first is not None and last is not None
    return EvaluationInputs(features, bars, calibration, first, last + 1)


def evaluate(
    alpha_id: str,
    split: Split,
    experiment_id: int,
    *,
    engine: Engine | None = None,
    config: EvaluationConfig | None = None,
    load_inputs: InputLoader | None = None,
    output_dir: Path = REPORT_DIR,
    actor: str = "",
    purpose: str = "",
    reported: bool = True,
) -> AlphaResult:
    """Persist one attempt, including INVALID, without promotion or TEST double-counting."""
    started = time.monotonic()
    split = Split(split)
    selected = (
        EvaluationConfig()
        if config is None
        else EvaluationConfig.model_validate(config.model_dump())
    )
    engine = get_engine() if engine is None else engine
    splits, fees, gates = load_splits(), load_fees(), load_gates()
    with engine.begin() as connection:
        definition = _definition(connection, alpha_id, selected.version)
        experiment = require_open_experiment(connection, experiment_id)
        if experiment.snapshot_id is None:
            raise RegistryError("evaluation requires a preregistered data snapshot")
        stored_gate = get_gate_config(connection, gates.version)
        if stored_gate.config_hash != config_hash(gates):
            raise RegistryError("stored gate settings do not match accepted configuration")
    family = {"1h": HorizonFamily.HOURLY, "1m": HorizonFamily.MINUTE}[selected.interval]
    if definition.horizon_family is not family or (
        definition.expression is None and definition.provenance is not AlphaProvenance.ML
    ):
        raise RegistryError(
            "evaluator interval must match the registered expression or frozen ML family"
        )
    if selected.interval == "1m" and split is Split.TRAIN:
        raise RegistryError(
            "minute TRAIN regime evaluation needs a separate earlier calibration policy"
        )
    protocol = {
        "evaluation": selected.model_dump(mode="json"),
        "definition": definition.model_dump(mode="json"),
        "split": split.value,
        "splits": splits.model_dump(mode="json"),
        "fees": fees.model_dump(mode="json"),
        "gates": gates.model_dump(mode="json"),
        "calibration": "pre-TRAIN December 2017 for TRAIN; TRAIN for VALID/TEST; "
        "on-grid calibration only"
        if selected.interval == "1h"
        else "TRAIN-only minute regime calibration",
    }
    context = RunContext.capture(selected, experiment.snapshot_id, selected.seed, reported=reported)
    used: list[EvaluationInputs] = []
    feature_provenance: dict[str, Any] = {}
    computed_alpha: list[BoundedAlphaSeries] = []

    def loader(window: SplitWindow) -> tuple[BoundedAlphaSeries, pd.DataFrame]:
        if load_inputs is None:
            snapshot = load_manifest(experiment.snapshot_id or "")
            if selected.symbol not in snapshot.symbols or snapshot.interval != selected.interval:
                raise RegistryError("snapshot does not contain the requested symbol/interval")
            # Verify snapshot bytes without parsing observations in unrequested splits.
            first_year = (
                2017 if selected.interval == "1h" else splits.families[family].train.start.year
            )
            years = range(first_year, pd.Timestamp(window.end_us - 1, unit="us").year + 1)
            for file in snapshot.files:
                if f"symbol={selected.symbol}/" in file.path and any(
                    f"year={year}/" in file.path for year in years
                ):
                    if sha256_file(DEFAULT_OUT_DIR / file.path) != file.sha256:
                        raise RegistryError("bar snapshot checksum mismatch")
            feature_config = DatasetConfig(
                interval=selected.interval,
                features=tuple(REGISTRY.names()),
                feature_set_version=definition.feature_set_version,
            )
            root = (
                DEFAULT_FEATURE_DIR
                / f"feature_set={feature_config.feature_set_version}"
                / f"interval={selected.interval}"
                / f"symbol={selected.symbol}"
            )
            manifest_path = root / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            registered = {f.path: f.sha256 for f in snapshot.files}
            for file in manifest["input_snapshot"]["files"]:
                if registered.get(file["path"]) != file["sha256"]:
                    raise RegistryError("feature source does not match registered bars snapshot")
            for file in manifest["files"]:
                if any(f"year={year}/" in file["path"] for year in years):
                    path = (root / file["path"]).resolve()
                    if (
                        not path.is_relative_to(root.resolve())
                        or sha256_file(path) != file["sha256"]
                    ):
                        raise RegistryError("feature-store checksum mismatch")
            feature_provenance.update(
                manifest_sha256=sha256_file(manifest_path), lineage=manifest["lineage"]
            )
            inputs = stored_inputs(window, definition, symbol=selected.symbol)
        else:
            inputs = load_inputs(window, definition)
        used.append(inputs)
        if definition.expression is None:
            alpha, ml_evidence = frozen_ml_series(
                definition, window, symbol=selected.symbol, snapshot_id=experiment.snapshot_id or ""
            )
            feature_provenance["ml"] = ml_evidence
        else:
            alpha = evaluate_definition(definition, inputs.features, interval=selected.interval)
        computed_alpha.append(alpha)
        return alpha, inputs.bars

    evaluation = evaluate_split(
        engine,
        experiment_id=experiment_id,
        alpha_id=alpha_id,
        version=selected.version,
        split=split,
        interval=selected.interval,
        horizon_periods=definition.horizon_periods,
        load_inputs=loader,
        validity_config=ValidityConfig(
            warmup_rows=selected.warmup_rows, min_periods=selected.min_periods
        ),
        fees=fees,
        splits=splits,
        actor=actor,
        purpose=purpose,
    )
    inputs = used[0]
    evidence: dict[str, Any] = {
        "feature_provenance": feature_provenance,
        "mode": "BACKTEST",
        "protocol": protocol,
        "validity": evaluation.validity,
        "snapshot_id": experiment.snapshot_id,
        "status": "INVALID",
        "series": [],
    }
    fit = stability = costs = None
    if evaluation.validity.valid:
        assert evaluation.diagnostics is not None and evaluation.simulation is not None
        fit = fitness_result(evaluation.diagnostics, gates=gates)
        regime = fit_volatility_regimes(
            inputs.calibration,
            calibration_start_us=inputs.calibration_start_us,
            calibration_end_us=inputs.calibration_end_us,
            config=StabilityConfig(interval=selected.interval),
        )
        stability = stability_report(evaluation.simulation, inputs.features, regime, splits=splits)
        costs = cost_sensitivity(evaluation.simulation.gross, fees=fees, splits=splits)
        report = evaluate_gates(
            evaluation, fitness=fit, stability=stability, costs=costs, gates=gates
        )
        evidence.update(
            status=report.status,
            diagnostics=evaluation.diagnostics,
            fitness=fit,
            stability=stability,
            costs=costs,
        )
        table = evaluation.simulation.table
        evidence["series"] = json.loads(
            table[["open_time", "net_return", "gross_return", "cost", "position"]].to_json(
                orient="records", double_precision=15
            )
        )
        alpha = computed_alpha[0]
        keep = alpha.open_time >= int(table.open_time.iloc[0])
        alpha = replace(
            alpha,
            open_time=alpha.open_time.loc[keep],
            values=alpha.values.loc[keep],
            available=alpha.available.loc[keep],
        )
        evidence["ic"] = information_coefficients(
            {selected.symbol: alpha},
            {
                selected.symbol: inputs.bars.loc[
                    inputs.bars.open_time >= int(table.open_time.iloc[0])
                ]
            },
            config=ICConfig(interval=selected.interval, horizon=definition.horizon_periods),
            snapshot_id=experiment.snapshot_id,
        )
    else:
        report = evaluate_gates(evaluation, gates=gates)
    evidence["gates"] = report
    evidence["source"] = {
        "commit": context.code_commit,
        "dirty": context.dirty,
        "seed": context.seed,
    }
    run_id = str(uuid.uuid4())
    encoded = json.dumps(evidence, default=_encode, sort_keys=True, allow_nan=False).encode()
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact = output_dir / f"{run_id}.json"
    with artifact.open("xb") as file:
        file.write(encoded)
    metadata = {
        "test_access_id": None
        if evaluation.test_access is None
        else evaluation.test_access.access_id,
        "status": report.status,
        "artifact": str(artifact),
        "artifact_sha256": hashlib.sha256(encoded).hexdigest(),
        "protocol": protocol,
        "gate_config_hash": report.gate_config_hash,
        "validity": json.loads(json.dumps(evaluation.validity, default=_encode)),
    }
    metrics = None if evaluation.diagnostics is None else evaluation.diagnostics.base.metrics

    def number(value: float | None) -> Decimal | None:
        return None if value is None else Decimal(str(value))

    result = AlphaResult(
        run_id=run_id,
        experiment_id=experiment_id,
        alpha_id=alpha_id,
        version=selected.version,
        split=split,
        snapshot_id=experiment.snapshot_id,
        gate_config_id=gates.version,
        sharpe=number(None if metrics is None else metrics.annual_sharpe),
        annual_return=number(None if metrics is None else metrics.annual_return),
        turnover=number(
            None if evaluation.diagnostics is None else evaluation.diagnostics.mean_turnover
        ),
        fitness=number(None if fit is None else fit.value),
        periods=evaluation.validity.n_periods,
        max_drawdown=number(
            None if evaluation.diagnostics is None else -evaluation.diagnostics.drawdown.magnitude
        ),
        hit_rate=number(
            None if evaluation.diagnostics is None else evaluation.diagnostics.hit_rate
        ),
        cost_stress_sharpe=number(None if costs is None else costs.cost_stress_sharpe),
        stability_positive_fraction=number(
            None if stability is None else stability.positive_month_fraction
        ),
        gate_results={g.gate: g.passed for g in report.outcomes},
        status=Status(report.status),
        code_commit=context.code_commit,
        dirty=context.dirty,
        seed=context.seed,
        config_hash=hashlib.sha256(json.dumps(protocol, sort_keys=True).encode()).hexdigest(),
        evaluation_json=metadata,
        runtime_seconds=Decimal(str(time.monotonic() - started)),
    )
    with engine.begin() as connection:
        if evaluation.test_access is not None:
            access = connection.execute(
                text(
                    "SELECT alpha_id,version,snapshot_id FROM test_set_access WHERE access_id=:id"
                ),
                {"id": evaluation.test_access.access_id},
            ).one()
            if tuple(access) != (alpha_id, selected.version, experiment.snapshot_id):
                raise RegistryError("TEST reservation changed")
        return record_result(connection, result)
