"""Local PAPER-only control; the shared risk trip and audit commit atomically."""

import json
from time import time_ns

from sqlalchemy import Engine, text

from helios.common.config import config_hash
from helios.common.db import get_engine
from helios.common.types import ReasonCode
from helios.equities.paper_config import EquityPaperConfig
from helios.paper.config import PaperConfig
from helios.sim.loss_risk import RiskTrip, record_trip, tripped


def kill_paper(
    run_id: str, actor: str, justification: str, *, engine: Engine | None = None
) -> bool:
    actor, justification = actor.strip(), justification.strip()
    if not 2 <= len(actor) <= 80 or not 3 <= len(justification) <= 500:
        raise ValueError("operator name and a short justification are required")
    with (get_engine() if engine is None else engine).begin() as connection:
        row = connection.execute(
            text("""SELECT status,config_json,config_hash FROM paper_runs
            WHERE paper_run_id=:id AND mode='PAPER' AND is_simulated FOR UPDATE"""),
            dict(id=run_id),
        ).one_or_none()
        if row is None or row.status != "running":
            raise ValueError("kill control requires a running simulated PAPER session")
        config = (
            EquityPaperConfig.model_validate(row.config_json)
            if row.config_json.get("version") == "nse_public_minute_paper_v1"
            else PaperConfig.model_validate(row.config_json)
        )
        if config.run_id != run_id or config_hash(config) != row.config_hash:
            raise ValueError("PAPER control requires matching session lineage")
        before = tripped(connection, run_id)
        now = time_ns() // 1000
        record_trip(
            connection,
            RiskTrip(
                scope=run_id,
                timestamp=now,
                reason=ReasonCode.HALTED,
                limits_hash=config_hash(config.risk),
                actor=actor,
            ),
        )
        connection.execute(
            text("""INSERT INTO audit_events (ts,actor,action,subject,justification,payload)
            VALUES (:ts,:actor,'PAPER_KILL_REQUEST',:scope,:reason,CAST(:payload AS jsonb))"""),
            dict(
                ts=now,
                actor=actor,
                scope=run_id,
                reason=justification,
                payload=json.dumps(
                    dict(
                        mode="PAPER",
                        is_simulated=True,
                        already_halted=before,
                        config_hash=row.config_hash,
                    )
                ),
            ),
        )
        return not before
