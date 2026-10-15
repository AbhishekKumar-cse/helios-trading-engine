"""Consistent, uncached views of persisted simulated PAPER checkpoints."""

from typing import Any

from sqlalchemy import Connection, Engine, bindparam, text

from helios.common.db import get_engine
from helios.sim.loss_risk import tripped
from helios.sim.strategy import WORKING_STATES


def paper_rows(connection: Connection, run_id: str | None = None) -> dict[str, Any]:
    runs = [
        dict(row)
        for row in connection.execute(
            text("""SELECT paper_run_id,status,created_at FROM paper_runs
            WHERE mode='PAPER' AND is_simulated ORDER BY created_at DESC,paper_run_id""")
        ).mappings()
    ]
    if not runs:
        return dict(runs=[], run=None)
    selected = run_id if run_id is not None else runs[0]["paper_run_id"]
    run = (
        connection.execute(
            text(
                "SELECT * FROM paper_runs WHERE paper_run_id=:id AND mode='PAPER' AND is_simulated"
            ),
            dict(id=selected),
        )
        .mappings()
        .one_or_none()
    )
    if run is None:
        raise ValueError("unknown simulated PAPER session")
    params = dict(id=selected)
    pnl = (
        connection.execute(
            text("""SELECT ts,realised,unrealised,fees,total,cash,gross_exposure,net_exposure
        FROM pnl_snapshots WHERE paper_run_id=:id ORDER BY ts DESC LIMIT 1"""),
            params,
        )
        .mappings()
        .one_or_none()
    )
    positions = (
        connection.execute(
            text("""SELECT DISTINCT ON (p.instrument_id)
        i.symbol,p.ts,p.net_qty,p.avg_cost,p.mark_px,
        p.realised_pnl,p.unrealised_pnl FROM positions_snapshot p
        JOIN instruments i USING(instrument_id) WHERE p.paper_run_id=:id
        ORDER BY p.instrument_id,p.ts DESC"""),
            params,
        )
        .mappings()
        .all()
    )
    orders = (
        connection.execute(
            text("""SELECT o.order_id,i.symbol,o.side,o.qty,o.remaining_qty,o.status,o.ts_created
        FROM orders o JOIN instruments i USING(instrument_id)
        WHERE o.paper_run_id=:id AND o.is_simulated AND o.status IN :states
        ORDER BY o.ts_created,o.order_id""").bindparams(bindparam("states", expanding=True)),
            params | dict(states=[s.value for s in WORKING_STATES]),
        )
        .mappings()
        .all()
    )
    return dict(
        runs=runs,
        run=dict(run),
        pnl=None if pnl is None else dict(pnl),
        positions=[dict(p) for p in positions],
        orders=[dict(o) for o in orders],
        halted=tripped(connection, selected),
    )


def read_paper(run_id: str | None = None, *, engine: Engine | None = None) -> dict[str, Any]:
    with (get_engine() if engine is None else engine).connect() as connection:
        connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        return paper_rows(connection, run_id)
