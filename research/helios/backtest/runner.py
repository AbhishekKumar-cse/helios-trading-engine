"""Preregister, reserve, replay and atomically persist simulated backtests (149)."""

import hashlib
import json
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Literal

from sqlalchemy import Connection, Engine, text

from helios.backtest.config import BacktestConfig
from helios.backtest.engine import ReplayTrace, simulate
from helios.backtest.inputs import load_inputs
from helios.common.config import config_hash
from helios.common.db import get_engine
from helios.common.lineage import RunContext
from helios.common.project_config import HorizonFamily
from helios.common.types import AlphaValue, Bar, Record
from helios.data.binance import sha256_file
from helios.data.snapshots import Snapshot, SnapshotFile, compute_snapshot_id, register_snapshot
from helios.registry.api import AlphaDefinition, get_alpha, register_definition
from helios.registry.experiments import (
    ExperimentKind,
    ExperimentStatus,
    register_experiment,
    require_open_experiment,
    set_status,
)
from helios.sim.loss_risk import PostgresTripStore
from helios.sim.paper import rounded
from helios.sim.splits import split_window

OUTPUT = Path(__file__).resolve().parents[3] / "reports_out/backtests"


class BacktestArtifact(Record):
    version: Literal["bar_backtest_artifact_v1"] = "bar_backtest_artifact_v1"
    mode: Literal["BACKTEST"] = "BACKTEST"
    is_simulated: Literal[True] = True
    config: BacktestConfig
    context: RunContext
    input_sha256: str
    bars: tuple[Bar, ...]
    signals: tuple[AlphaValue, ...]
    trace: ReplayTrace


def _protocol_hash(config: BacktestConfig) -> str:
    return hashlib.sha256(json.dumps(config.protocol(), sort_keys=True).encode()).hexdigest()


def _instrument(connection: Connection, symbol: str) -> int:
    value = connection.execute(
        text("SELECT instrument_id FROM instruments WHERE symbol=:symbol"), {"symbol": symbol}
    ).scalar_one_or_none()
    if value is None:
        raise ValueError("backtest instrument must already be registered")
    return int(value)


def preregister(
    config: BacktestConfig, *, engine: Engine | None = None, reported: bool = True
) -> BacktestConfig:
    if config.experiment_id is not None:
        raise ValueError("preregistration requires an unbound config")
    engine = get_engine() if engine is None else engine
    context = RunContext.capture(config, config.snapshot_id, config.seed, reported=reported)
    with engine.begin() as connection:
        connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:id))"), {"id": "backtest:" + config.run_id}
        )
        if connection.execute(
            text(
                "SELECT EXISTS(SELECT 1 FROM experiments WHERE params->'protocol'->>'run_id'=:id)"
            ),
            {"id": config.run_id},
        ).scalar_one():
            raise ValueError("run ID already preregistered; retain the original attempt")
        _instrument(connection, config.symbol)
        if config.data_kind == "synthetic_csv":
            assert config.csv_path is not None
            path = Path(config.csv_path)
            if sha256_file(path) != config.csv_sha256:
                raise ValueError("synthetic CSV checksum changed before preregistration")
            file = SnapshotFile(config.csv_path, config.csv_sha256 or "", path.stat().st_size)
            if compute_snapshot_id([file]) != config.snapshot_id:
                raise ValueError("synthetic snapshot must anchor the exact CSV path and hash")
            register_snapshot(
                connection,
                Snapshot(
                    config.snapshot_id,
                    "synthetic_correctness_fixture",
                    "1h",
                    [config.symbol],
                    config.start_us,
                    config.end_us - 3_600_000_000,
                    1,
                    (config.end_us - config.start_us) // 3_600_000_000,
                    file.bytes,
                    context.code_commit,
                    [file],
                ),
            )
            expected = AlphaDefinition(
                alpha_id=config.alpha_id,
                version=config.alpha_version,
                name="Synthetic bar correctness fixture",
                feature_set_version="synthetic_hand_v1",
                horizon_family=HorizonFamily.HOURLY,
                horizon_periods=1,
                author="helios_backtest",
                code_commit=context.code_commit,
                spec={"synthetic_csv_sha256": config.csv_sha256, "is_synthetic": True},
            )
            exists = connection.execute(
                text(
                    "SELECT count(*) FROM alpha_definitions WHERE alpha_id=:id AND version=:version"
                ),
                {"id": config.alpha_id, "version": config.alpha_version},
            ).scalar_one()
            if exists:
                if (
                    get_alpha(connection, config.alpha_id, config.alpha_version).spec
                    != expected.spec
                ):
                    raise ValueError("immutable synthetic alpha definition differs")
            else:
                register_definition(connection, expected)
        experiment = register_experiment(
            connection,
            kind=ExperimentKind.BACKTEST,
            hypothesis=(
                "Replay the fixed bar strategy through shared risk/OMS/paper/ledger; "
                "preserve every fill, rejection and reconciled snapshot. "
                "Synthetic fixtures establish correctness only; no promotion or TEST."
            ),
            params={"protocol": config.protocol()},
            author="helios_backtest",
            snapshot_id=config.snapshot_id,
            code_commit=context.code_commit,
            config_hash=_protocol_hash(config),
        )
    return BacktestConfig.model_validate(
        config.model_dump() | {"experiment_id": experiment.experiment_id}
    )


def _persist(
    connection: Connection,
    config: BacktestConfig,
    trace: ReplayTrace,
    instrument: int,
    path: Path,
    digest: str,
) -> None:
    limits_hash = config_hash(config.risk)
    for order in trace.orders:
        request = order.request
        reports = [r for r in trace.reports if r.order_id == order.order_id]
        fills = [r.fill for r in reports if r.fill is not None]
        connection.execute(
            text("""INSERT INTO orders
            (order_id,client_order_id,strategy_id,alpha_id,alpha_version,instrument_id,
             side,order_type,price,qty,remaining_qty,filled_qty,avg_fill_px,tif,status,
             ts_created,ts_submitted,ts_ack,ts_terminal,venue_order_id,venue_id,
             is_simulated,limits_snapshot_hash,bt_run_id)
            VALUES (:id,:client,:strategy,:alpha,:version,:instrument,:side,:type,:price,:qty,
             :remaining,:filled,:average,:tif,:status,:created,:submitted,:ack,:terminal,
             :id,'bar-paper',true,:limits,:run)"""),
            dict(
                id=order.order_id,
                client=request.client_order_id,
                strategy=config.run_id,
                alpha=config.alpha_id,
                version=config.alpha_version,
                instrument=instrument,
                side=request.side.value,
                type=request.order_type.value,
                price=request.price,
                qty=request.quantity,
                remaining=order.remaining_quantity,
                filled=order.filled_quantity,
                average=fills[0].price if fills else None,
                tif=request.time_in_force.value,
                status=order.state.value,
                created=request.timestamp,
                submitted=reports[0].timestamp if reports else None,
                ack=reports[0].timestamp if reports else None,
                terminal=order.timestamp if fills else None,
                limits=limits_hash,
                run=config.run_id,
            ),
        )
        for fill in fills:
            connection.execute(
                text("""INSERT INTO fills
                (fill_id,order_id,instrument_id,side,price,qty,liquidity_flag,fee,
                 ts_venue,ts_received,venue_id)
                VALUES (:id,:order,:instrument,:side,:price,:qty,
                        :liquidity,:fee,:ts,:ts,:venue)"""),
                dict(
                    id=fill.fill_id,
                    order=fill.order_id,
                    instrument=instrument,
                    side=fill.side.value,
                    price=fill.price,
                    qty=fill.quantity,
                    liquidity=fill.liquidity,
                    fee=fill.fee,
                    ts=fill.timestamp,
                    venue=fill.venue_id,
                ),
            )
    for snapshot, position, mark in zip(trace.snapshots, trace.positions, trace.marks, strict=True):
        with localcontext() as context:
            context.prec = 100
            exposure = rounded(position.quantity * mark)
            total = snapshot.realized_pnl + snapshot.unrealized_pnl - snapshot.fees
        connection.execute(
            text("""INSERT INTO pnl_snapshots
            (scope,ts,strategy_id,realised,unrealised,fees,total,gross_exposure,net_exposure,cash,bt_run_id)
            VALUES (:run,:ts,:run,:realized,:unrealized,:fees,:total,:gross,:net,:cash,:run)"""),
            dict(
                run=config.run_id,
                ts=snapshot.timestamp,
                realized=snapshot.realized_pnl,
                unrealized=snapshot.unrealized_pnl,
                fees=snapshot.fees,
                total=total,
                gross=abs(exposure),
                net=exposure,
                cash=snapshot.cash,
            ),
        )
        connection.execute(
            text("""INSERT INTO positions_snapshot
            (scope,instrument_id,ts,strategy_id,net_qty,avg_cost,realised_pnl,unrealised_pnl,mark_px,bt_run_id)
            VALUES (:run,:instrument,:ts,:run,:qty,:avg,:realized,:unrealized,:mark,:run)"""),
            dict(
                run=config.run_id,
                instrument=instrument,
                ts=snapshot.timestamp,
                qty=position.quantity,
                avg=position.average_entry_price or Decimal(0),
                realized=snapshot.realized_pnl,
                unrealized=snapshot.unrealized_pnl,
                mark=mark,
            ),
        )
    for index, decision in enumerate(trace.decisions):
        if decision.accepted:
            continue
        connection.execute(
            text("""INSERT INTO risk_events
            (event_id,ts,type,severity,reason_code,subject_ref,limits_snapshot_hash,actor)
            VALUES (:id,:ts,'ORDER_REJECTED','WARNING',:reason,:scope,:hash,'backtest')"""),
            dict(
                id=f"{config.run_id}:reject:{index}",
                ts=decision.timestamp,
                reason=decision.reason.value,
                scope=config.run_id,
                hash=limits_hash,
            ),
        )
    connection.execute(
        text("""UPDATE backtest_runs SET status='finished',results_ref=:path,
        artifact_sha256=:digest WHERE bt_run_id=:id AND status='running'"""),
        dict(path=str(path), digest=digest, id=config.run_id),
    )


def run_backtest(
    config: BacktestConfig,
    *,
    engine: Engine | None = None,
    output_dir: Path = OUTPUT,
    reported: bool = True,
) -> Path:
    config = BacktestConfig.model_validate(config.model_dump())
    if config.experiment_id is None:
        raise ValueError("backtest requires preregistration before loading inputs")
    engine = get_engine() if engine is None else engine
    context = RunContext.capture(config, config.snapshot_id, config.seed, reported=reported)
    with engine.begin() as connection:
        connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:id))"), {"id": "backtest:" + config.run_id}
        )
        if connection.execute(
            text("SELECT count(*) FROM backtest_runs WHERE bt_run_id=:id"), {"id": config.run_id}
        ).scalar_one():
            raise ValueError("run ID already consumed; no overwrite or silent retry")
        experiment = require_open_experiment(connection, config.experiment_id)
        if (
            experiment.kind is not ExperimentKind.BACKTEST
            or experiment.status is not ExperimentStatus.PLANNED
            or experiment.snapshot_id != config.snapshot_id
            or experiment.params.get("protocol") != config.protocol()
            or experiment.config_hash != _protocol_hash(config)
        ):
            raise ValueError("exact backtest config must be preregistered once")
        definition = get_alpha(connection, config.alpha_id, config.alpha_version)
        if definition.horizon_family is not HorizonFamily.HOURLY:
            raise ValueError("hourly runner requires an hourly definition")
        split_window(config.split, interval="1h", horizon_periods=definition.horizon_periods)
        snapshot = connection.execute(
            text("SELECT source,symbols,interval FROM data_snapshots WHERE snapshot_id=:id"),
            {"id": config.snapshot_id},
        ).one()
        if (
            config.symbol not in snapshot.symbols
            or snapshot.interval != "1h"
            or (snapshot.source.startswith("synthetic") != (config.data_kind == "synthetic_csv"))
        ):
            raise ValueError("snapshot source/universe does not match the configured input kind")
        instrument = _instrument(connection, config.symbol)
        connection.execute(
            text("""INSERT INTO strategies
            (strategy_id,alpha_id,alpha_version,params_json,code_commit)
            VALUES (:id,:alpha,:version,CAST(:params AS jsonb),:commit)"""),
            dict(
                id=config.run_id,
                alpha=config.alpha_id,
                version=config.alpha_version,
                params=config.strategy.model_dump_json(),
                commit=context.code_commit,
            ),
        )
        connection.execute(
            text("""INSERT INTO risk_limits
            (limit_set_id,scope,version,limits,author,effective_from,hash)
            VALUES (:id,:id,1,CAST(:limits AS jsonb),'backtest',now(),:hash)"""),
            dict(
                id=config.run_id,
                limits=config.risk.model_dump_json(),
                hash=config_hash(config.risk),
            ),
        )
        connection.execute(
            text("""INSERT INTO backtest_runs
            (bt_run_id,experiment_id,strategy_id,data_snapshot_id,code_commit,config_hash,seed,
             fill_model_ref,cost_model_ref,status,mode,dirty,config_json)
            VALUES (:id,:experiment,:id,:snapshot,:commit,:hash,:seed,
             'bar_next_open_full_fill_v1',:fees,'running','BACKTEST',:dirty,
             CAST(:config AS jsonb))"""),
            dict(
                id=config.run_id,
                experiment=config.experiment_id,
                snapshot=config.snapshot_id,
                commit=context.code_commit,
                hash=config_hash(config),
                seed=config.seed,
                fees=config_hash(config.fees),
                dirty=context.dirty,
                config=config.model_dump_json(),
            ),
        )
        set_status(connection, config.experiment_id, ExperimentStatus.RUNNING)
    try:
        inputs = load_inputs(config, definition, context)
        trace = simulate(config, inputs.bars, inputs.signals, PostgresTripStore(engine))
        artifact = BacktestArtifact(
            config=config,
            context=context,
            input_sha256=inputs.sha256,
            bars=inputs.bars,
            signals=inputs.signals,
            trace=trace,
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        path = (output_dir / f"{config.run_id}.json").resolve()
        with path.open("x") as handle:
            handle.write(artifact.model_dump_json(indent=2) + "\n")
        with engine.begin() as connection:
            _persist(connection, config, trace, instrument, path, sha256_file(path))
            set_status(connection, config.experiment_id, ExperimentStatus.FINISHED)
        return path
    except Exception:
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE backtest_runs SET status='failed' WHERE bt_run_id=:id"),
                {"id": config.run_id},
            )
            set_status(connection, config.experiment_id, ExperimentStatus.ABANDONED)
        raise
