"""Reconcile a crashed, leased NSE PAPER scope and close it halted.

This never resumes trading, invents an exit fill, or resets non-flat inventory.
Only v2 session identities (whose runner takes an exclusive lease) are eligible.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections.abc import Mapping, Sequence
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, text

from helios.common.config import config_hash
from helios.common.db import get_engine
from helios.common.types import BookView, Fill, Mode, ReasonCode
from helios.data.equities import sha256
from helios.equities.paper_config import EquityPaperConfig
from helios.paper.lease import paper_lease
from helios.registry.experiments import ExperimentStatus, set_status
from helios.sim.ledger import PnLLedger
from helios.sim.loss_risk import RiskTrip, record_trip

WORKING = ("NEW", "PENDING_NEW", "ACK", "PARTIALLY_FILLED", "PENDING_CANCEL")


def reconcile_records(
    config: EquityPaperConfig,
    orders: Sequence[Mapping[str, Any]],
    fills: Sequence[Mapping[str, Any]],
    pnl: Sequence[Mapping[str, Any]],
    positions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Replay durable fills and verify every paired ledger/position checkpoint."""
    ledger = PnLLedger(
        config.strategy.capital,
        Mode.PAPER,
        "INR",
        symbols=(config.symbol,),
        mark_reference="public_last_price_proxy",
    )
    by_order = {row["order_id"]: row for row in orders}
    if len(by_order) != len(orders) or len(pnl) != len(positions):
        raise ValueError("duplicate order or unmatched position/PnL checkpoint")
    observed: dict[str, Decimal] = dict.fromkeys(by_order, Decimal(0))
    typed = []
    for row in fills:
        order = by_order.get(row["order_id"])
        if (
            order is None
            or not order["is_simulated"]
            or order["venue_id"] != "bar-paper"
            or row["side"] != order["side"]
            or row["ts_venue"] <= order["ts_created"]
            or row["symbol"] != config.symbol
            or row["quote_asset"] != "INR"
            or row["instrument_id"] != order["instrument_id"]
            or row["ts_received"] < row["ts_venue"]
            or row["venue_id"] != "bar-paper"
            or row["qty"] != row["qty"].to_integral_value()
        ):
            raise ValueError("persisted fill identity, chronology or whole-share mismatch")
        typed.append(
            Fill(
                fill_id=row["fill_id"],
                order_id=row["order_id"],
                symbol=config.symbol,
                side=row["side"],
                quantity=row["qty"],
                price=row["price"],
                fee=row["fee"],
                fee_asset="INR",
                timestamp=row["ts_venue"],
                venue_id=row["venue_id"],
                liquidity=row["liquidity_flag"],
                mode=Mode.PAPER,
            )
        )
        observed[row["order_id"]] += row["qty"]
    if len({f.fill_id for f in typed}) != len(typed):
        raise ValueError("duplicate durable fill identity")
    # The v1 venue fully fills a single intent at a time. Refuse an ordering we
    # cannot infer from these persisted records rather than guessing a tie-break.
    stamps = [f.timestamp for f in typed]
    if stamps != sorted(set(stamps)):
        raise ValueError("ambiguous or unordered persisted fill chronology")
    for order in orders:
        if (
            order["filled_qty"] != observed[order["order_id"]]
            or order["qty"] != order["remaining_qty"] + order["filled_qty"]
            or order["symbol"] != config.symbol
            or order["quote_asset"] != "INR"
            or order["strategy_id"] != config.run_id
            or order["alpha_id"] != config.alpha_id
            or order["alpha_version"] != config.alpha_version
            or not order["is_simulated"]
            or order["venue_id"] != "bar-paper"
            or order["limits_snapshot_hash"] != config_hash(config.risk)
            or order["status"] not in (*WORKING, "FILLED", "CANCELLED", "EXPIRED", "REJECTED")
            or (order["status"] == "FILLED" and order["remaining_qty"] != 0)
        ):
            raise ValueError("persisted order/fill conservation or ownership mismatch")
    index, previous, snapshot = 0, -1, None
    for p, pos in zip(pnl, positions, strict=True):
        stamp = p["ts"]
        if (
            stamp <= previous
            or stamp != pos["ts"]
            or pos["symbol"] != config.symbol
            or pos["quote_asset"] != "INR"
            or p["scope"] != config.run_id
            or pos["scope"] != config.run_id
            or p["strategy_id"] != config.run_id
            or pos["strategy_id"] != config.run_id
        ):
            raise ValueError("checkpoint chronology or instrument mismatch")
        while index < len(typed) and typed[index].timestamp <= stamp:
            ledger.book(typed[index])
            index += 1
        snapshot = ledger.snapshot(
            stamp,
            {
                config.symbol: BookView(
                    symbol=config.symbol,
                    timestamp=stamp,
                    sequence=0,
                    best_bid=pos["mark_px"],
                    best_ask=pos["mark_px"],
                    stale=False,
                )
            },
        )
        position = ledger.position(config.symbol)
        with localcontext() as context:
            context.prec = 100
            checks = (
                snapshot.cash == p["cash"],
                snapshot.fees == p["fees"],
                snapshot.realized_pnl == p["realised"],
                snapshot.unrealized_pnl == p["unrealised"],
                snapshot.realized_pnl + snapshot.unrealized_pnl - snapshot.fees == p["total"],
                position.quantity == pos["net_qty"],
                (position.average_entry_price or Decimal(0)) == pos["avg_cost"],
                pos["realised_pnl"] == snapshot.realized_pnl,
                pos["unrealised_pnl"] == snapshot.unrealized_pnl,
                p["net_exposure"] == position.quantity * pos["mark_px"],
                p["gross_exposure"] == abs(p["net_exposure"]),
            )
        if not all(checks):
            raise ValueError("durable ledger checkpoint does not reconcile with fills")
        previous = stamp
    if index != len(typed) or (orders and snapshot is None):
        raise ValueError("orders/fills lack a final durable accounting checkpoint")
    return dict(
        status="RECONCILED",
        fills=len(typed),
        checkpoints=len(pnl),
        cash=str(config.strategy.capital if snapshot is None else snapshot.cash),
        fees=str(Decimal(0) if snapshot is None else snapshot.fees),
        position=ledger.position(config.symbol).model_dump(mode="json"),
        last_mark=None if not positions else str(positions[-1]["mark_px"]),
        mark_is_historical=True,
        automatic_resume=False,
    )


def recover_equity_paper(
    run_id: str,
    actor: str,
    *,
    root: Path = Path("reports_out/equity_paper"),
    engine: Engine | None = None,
) -> Path:
    """Lease, latch kill, reconcile and atomically terminalize a crashed run.

    A failed reconciliation still closes the scope failed and retains evidence.
    Fills and historical snapshots are never changed. Cancellation applies only
    to this dead process's simulated, in-memory venue, which cannot later fill.
    """
    actor = actor.strip()
    if (
        not 2 <= len(actor) <= 80
        or not run_id
        or any(
            c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
            for c in run_id
        )
        or len(run_id) > 40
    ):
        raise ValueError("valid recovery scope and operator required")
    engine = get_engine() if engine is None else engine
    destination = root / run_id
    identity = destination / "session.json"
    session = json.loads(identity.read_text())
    if (
        session.get("version") != "nse_paper_session_v2"
        or session.get("ownership") != "postgres_session_advisory_lock_v1"
        or session.get("run_id") != run_id
    ):
        raise ValueError("recovery requires the leased v2 session identity")
    with paper_lease(engine, run_id), engine.begin() as connection:
        row = (
            connection.execute(
                text("SELECT * FROM paper_runs WHERE paper_run_id=:id FOR UPDATE"), dict(id=run_id)
            )
            .mappings()
            .one()
        )
        config = EquityPaperConfig.model_validate(row["config_json"])
        if (
            row["status"] != "running"
            or row["mode"] != "PAPER"
            or not row["is_simulated"]
            or row["dirty"]
            or config.run_id != run_id
            or config_hash(config) != row["config_hash"]
            or config.stream_id != row["stream_id"]
            or sha256(identity) != config.stream_id
            or session.get("code_commit") != row["code_commit"]
            or session.get("symbol") != config.symbol
        ):
            raise ValueError("recovery requires matching running simulated session lineage")
        now = time.time_ns() // 1000
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
        params = dict(id=run_id)
        orders = list(
            connection.execute(
                text(
                    "SELECT o.*,i.symbol,i.quote_asset FROM orders o "
                    "JOIN instruments i USING(instrument_id) "
                    "WHERE o.paper_run_id=:id ORDER BY o.ts_created,o.order_id FOR UPDATE OF o"
                ),
                params,
            ).mappings()
        )
        fills = list(
            connection.execute(
                text(
                    "SELECT f.*,i.symbol,i.quote_asset FROM fills f JOIN orders o USING(order_id) "
                    "JOIN instruments i ON i.instrument_id=f.instrument_id "
                    "WHERE o.paper_run_id=:id ORDER BY f.ts_venue,f.fill_id"
                ),
                params,
            ).mappings()
        )
        pnl = list(
            connection.execute(
                text("SELECT * FROM pnl_snapshots WHERE paper_run_id=:id ORDER BY ts"), params
            ).mappings()
        )
        positions = list(
            connection.execute(
                text(
                    "SELECT p.*,i.symbol,i.quote_asset FROM positions_snapshot p "
                    "JOIN instruments i USING(instrument_id) WHERE p.paper_run_id=:id ORDER BY p.ts"
                ),
                params,
            ).mappings()
        )
        try:
            reconciliation = reconcile_records(
                config,
                [dict(r) for r in orders],
                [dict(r) for r in fills],
                [dict(r) for r in pnl],
                [dict(r) for r in positions],
            )
        except (ValueError, ArithmeticError) as exc:
            reconciliation = dict(status="MISMATCH", reason=str(exc), automatic_resume=False)
        cancelled = [o["order_id"] for o in orders if o["status"] in WORKING]
        connection.execute(
            text(
                "UPDATE orders SET status='CANCELLED',ts_terminal=:now "
                "WHERE paper_run_id=:id AND status IN "
                "('NEW','PENDING_NEW','ACK','PARTIALLY_FILLED','PENDING_CANCEL')"
            ),
            dict(id=run_id, now=now),
        )
        record = dict(
            version="nse_paper_crash_recovery_v1",
            mode="PAPER",
            is_simulated=True,
            run_id=run_id,
            actor=actor,
            recovered_at=now,
            stream_identity_sha256=sha256(identity),
            config_hash=config_hash(config),
            reconciliation=reconciliation,
            cancelled_simulated_intents=cancelled,
            durable_records_sha256=hashlib.sha256(
                json.dumps(
                    [list(map(dict, rows)) for rows in (orders, fills, pnl, positions)],
                    sort_keys=True,
                    default=str,
                ).encode()
            ).hexdigest(),
            limitation="No broker reconciliation, automatic trading resume or invented exit fill.",
        )
        # Exclusive name: an uncommitted orphan after DB failure is retained and
        # a later recovery gets a new name. Never overwrite earlier evidence.
        artifact = destination / f"recovery_{now}.json"
        with artifact.open("x") as handle:
            handle.write(json.dumps(record, sort_keys=True, indent=2) + "\n")
        digest = sha256(artifact)
        connection.execute(
            text(
                "UPDATE paper_runs SET status='failed',artifact_ref=:path,artifact_sha256=:digest "
                "WHERE paper_run_id=:id AND status='running'"
            ),
            dict(id=run_id, path=str(artifact), digest=digest),
        )
        connection.execute(
            text("UPDATE strategies SET status='HALTED' WHERE strategy_id=:id"), params
        )
        set_status(connection, row["experiment_id"], ExperimentStatus.ABANDONED)
        connection.execute(
            text(
                "INSERT INTO audit_events(ts,actor,action,subject,justification,payload) "
                "VALUES (:now,:actor,'PAPER_CRASH_RECOVERY',:id,:reason,CAST(:payload AS jsonb))"
            ),
            dict(
                id=run_id,
                now=now,
                actor=actor,
                reason="Dead simulated process reconciled and halted",
                payload=json.dumps(
                    dict(
                        artifact_ref=str(artifact),
                        artifact_sha256=digest,
                        reconciliation=reconciliation["status"],
                    )
                ),
            ),
        )
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--root", type=Path, default=Path("reports_out/equity_paper"))
    args = parser.parse_args()
    print(recover_equity_paper(args.run_id, args.actor, root=args.root))


if __name__ == "__main__":
    main()
