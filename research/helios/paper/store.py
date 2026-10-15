"""Incremental PAPER database checkpoints; fills and snapshots stay append-only."""

from decimal import localcontext
from pathlib import Path

from sqlalchemy import Engine, text

from helios.common.config import config_hash
from helios.common.lineage import RunContext
from helios.paper.config import PaperConfig
from helios.paper.runtime import PaperRuntime
from helios.registry.experiments import (
    ExperimentKind,
    ExperimentStatus,
    register_experiment,
    set_status,
)
from helios.sim.paper import rounded


class PaperStore:
    def __init__(self, engine: Engine, config: PaperConfig, context: RunContext) -> None:
        if (
            context.dirty
            or context.config_hash != config_hash(config)
            or context.data_snapshot_id != config.stream_id
        ):
            raise ValueError("PAPER persistence requires matching clean session lineage")
        self.engine, self.config = engine, config
        self.n_reports = self.n_snapshots = self.n_decisions = 0
        with engine.begin() as connection:
            instrument: int = connection.execute(
                text("SELECT instrument_id FROM instruments WHERE symbol=:symbol"),
                dict(symbol=config.symbol),
            ).scalar_one()
            self.instrument = int(instrument)
            experiment = register_experiment(
                connection,
                kind=ExperimentKind.INFRASTRUCTURE,
                hypothesis="Fixed rejected minute reversal used only to verify observed-data PAPER "
                "strategy/risk/OMS/venue/ledger persistence; no promotion or TEST.",
                params=dict(protocol=config.model_dump(mode="json")),
                author="helios_paper",
                code_commit=context.code_commit,
                config_hash=config_hash(config),
            )
            self.experiment_id = experiment.experiment_id
            connection.execute(
                text("""INSERT INTO strategies
                (strategy_id,alpha_id,alpha_version,params_json,code_commit,status)
                VALUES (:id,:alpha,:version,CAST(:params AS jsonb),:commit,'ACTIVE')"""),
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
                VALUES (:id,:id,1,CAST(:limits AS jsonb),'paper',now(),:hash)"""),
                dict(
                    id=config.run_id,
                    limits=config.risk.model_dump_json(),
                    hash=config_hash(config.risk),
                ),
            )
            connection.execute(
                text("""INSERT INTO paper_runs
                (paper_run_id,experiment_id,strategy_id,mode,is_simulated,stream_id,code_commit,
                 dirty,config_hash,config_json,status)
                VALUES (:id,:experiment,:id,'PAPER',true,:stream,:commit,false,:hash,
                        CAST(:config AS jsonb),'running')"""),
                dict(
                    id=config.run_id,
                    experiment=self.experiment_id,
                    stream=config.stream_id,
                    commit=context.code_commit,
                    hash=config_hash(config),
                    config=config.model_dump_json(),
                ),
            )
            set_status(connection, self.experiment_id, ExperimentStatus.RUNNING)

    def save(self, runtime: PaperRuntime) -> None:
        trace, config = runtime.trace(), self.config
        with self.engine.begin() as connection:
            active: str = connection.execute(
                text("SELECT status FROM paper_runs WHERE paper_run_id=:id FOR UPDATE"),
                dict(id=config.run_id),
            ).scalar_one()
            if active != "running":
                raise ValueError("terminal PAPER session cannot accept checkpoints")
            for order in trace.orders:
                request = order.request
                reports = [r for r in trace.reports if r.order_id == order.order_id]
                fills = [r.fill for r in reports if r.fill is not None]
                result = connection.execute(
                    text("""INSERT INTO orders
                    (order_id,client_order_id,strategy_id,alpha_id,alpha_version,instrument_id,
                     side,order_type,price,qty,remaining_qty,filled_qty,avg_fill_px,tif,status,
                     ts_created,ts_submitted,ts_ack,ts_terminal,venue_order_id,venue_id,
                     is_simulated,limits_snapshot_hash,paper_run_id)
                    VALUES (:id,:client,:run,:alpha,:version,:instrument,:side,:type,:price,:qty,
                     :remaining,:filled,:average,:tif,:status,:created,:submitted,:ack,:terminal,
                     :id,'bar-paper',true,:limits,:run)
                    ON CONFLICT(order_id) DO UPDATE SET remaining_qty=EXCLUDED.remaining_qty,
                     filled_qty=EXCLUDED.filled_qty,avg_fill_px=EXCLUDED.avg_fill_px,status=EXCLUDED.status,
                     ts_ack=EXCLUDED.ts_ack,ts_terminal=EXCLUDED.ts_terminal
                    WHERE orders.paper_run_id=EXCLUDED.paper_run_id"""),
                    dict(
                        id=order.order_id,
                        client=request.client_order_id,
                        run=config.run_id,
                        alpha=config.alpha_id,
                        version=config.alpha_version,
                        instrument=self.instrument,
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
                        terminal=order.timestamp
                        if order.remaining_quantity == 0
                        or order.state.value in ("CANCELLED", "EXPIRED", "REJECTED")
                        else None,
                        limits=config_hash(config.risk),
                    ),
                )
                if result.rowcount != 1:
                    raise ValueError("PAPER order identity conflict")
            for report in trace.reports[self.n_reports :]:
                fill = report.fill
                if fill is None:
                    continue
                connection.execute(
                    text("""INSERT INTO fills
                    (fill_id,order_id,instrument_id,side,price,qty,liquidity_flag,fee,
                     ts_venue,ts_received,venue_id)
                    VALUES (:id,:order,:instrument,:side,:price,:qty,:liquidity,:fee,:ts,:ts,:venue)
                    """),
                    dict(
                        id=fill.fill_id,
                        order=fill.order_id,
                        instrument=self.instrument,
                        side=fill.side.value,
                        price=fill.price,
                        qty=fill.quantity,
                        fee=fill.fee,
                        liquidity=fill.liquidity,
                        ts=fill.timestamp,
                        venue=fill.venue_id,
                    ),
                )
            for i in range(self.n_snapshots, len(trace.snapshots)):
                snapshot, position, mark = trace.snapshots[i], trace.positions[i], trace.marks[i]
                with localcontext() as context:
                    context.prec = 100
                    exposure = rounded(position.quantity * mark)
                    total = snapshot.realized_pnl + snapshot.unrealized_pnl - snapshot.fees
                connection.execute(
                    text("""INSERT INTO pnl_snapshots
                    (scope,ts,strategy_id,realised,unrealised,fees,total,gross_exposure,
                     net_exposure,cash,paper_run_id)
                    VALUES (:run,:ts,:run,:realized,:unrealized,:fees,:total,:gross,:net,:cash,:run)
                    """),
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
                    (scope,instrument_id,ts,strategy_id,net_qty,avg_cost,realised_pnl,unrealised_pnl,
                     mark_px,paper_run_id)
                    VALUES (:run,:instrument,:ts,:run,:qty,:avg,:realized,:unrealized,:mark,:run)
                    """),
                    dict(
                        run=config.run_id,
                        instrument=self.instrument,
                        ts=snapshot.timestamp,
                        qty=position.quantity,
                        avg=position.average_entry_price or 0,
                        realized=snapshot.realized_pnl,
                        unrealized=snapshot.unrealized_pnl,
                        mark=mark,
                    ),
                )
            for i, decision in enumerate(trace.decisions[self.n_decisions :], self.n_decisions):
                if not decision.accepted:
                    connection.execute(
                        text("""INSERT INTO risk_events
                        (event_id,ts,type,severity,reason_code,subject_ref,limits_snapshot_hash,actor)
                        VALUES (:id,:ts,'ORDER_REJECTED','WARNING',:reason,:run,:hash,'paper')"""),
                        dict(
                            id=f"{config.run_id}:reject:{i}",
                            ts=decision.timestamp,
                            reason=decision.reason.value,
                            run=config.run_id,
                            hash=config_hash(config.risk),
                        ),
                    )
        self.n_reports, self.n_snapshots, self.n_decisions = (
            len(trace.reports),
            len(trace.snapshots),
            len(trace.decisions),
        )

    def finish(self, path: Path, digest: str, *, failed: bool) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text("""UPDATE paper_runs SET status=:status,
                artifact_ref=:path,artifact_sha256=:digest
                WHERE paper_run_id=:id AND status='running'"""),
                dict(
                    status="failed" if failed else "finished",
                    path=str(path),
                    digest=digest,
                    id=self.config.run_id,
                ),
            )
            connection.execute(
                text("UPDATE strategies SET status='HALTED' WHERE strategy_id=:id"),
                dict(id=self.config.run_id),
            )
            set_status(
                connection,
                self.experiment_id,
                ExperimentStatus.ABANDONED if failed else ExperimentStatus.FINISHED,
            )
