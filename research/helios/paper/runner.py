"""Bounded public-data PAPER session with durable checkpoints and exact artifacts."""

import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from sqlalchemy import Engine

from helios.common.db import get_engine
from helios.common.lineage import RunContext, git_commit, git_is_dirty
from helios.data.binance import sha256_file
from helios.data.live_klines import ClosedKline, KlineStreamError
from helios.data.resilient_klines import observe_resilient_klines
from helios.paper.config import smoke_config
from helios.paper.runtime import PaperRuntime, PaperSafetyStop
from helios.paper.store import PaperStore
from helios.sim.evaluate import _definition as registered_definition
from helios.sim.loss_risk import PostgresTripStore


async def run_paper(
    run_id: str,
    *,
    seconds: float = 240,
    endpoint: str = "spot443",
    root: Path = Path("reports_out/paper"),
    engine: Engine | None = None,
) -> Path:
    if git_is_dirty():
        raise ValueError("reported PAPER execution requires clean source")
    # Validate the run ID before using it as a path component.
    smoke_config(run_id, "0" * 64, seconds=seconds, endpoint=endpoint)
    destination = root / run_id
    destination.mkdir(parents=True, exist_ok=False)
    initial = destination / "session.json"
    initial.write_text(
        json.dumps(
            dict(
                version="paper_session_identity_v1",
                run_id=run_id,
                mode="PAPER",
                is_simulated=True,
                started_time=time.time_ns() // 1000,
                code_commit=git_commit(),
                seconds=seconds,
                endpoint=endpoint,
                symbol="BTCUSDT",
                purpose="integration_only_rejected_candidate",
                identity="session namespace; observed bytes hashed in terminal artifact",
            ),
            indent=2,
        )
        + "\n"
    )
    config = smoke_config(run_id, sha256_file(initial), seconds=seconds, endpoint=endpoint)
    context = RunContext.capture(config, config.stream_id, 0, reported=True)
    engine = get_engine() if engine is None else engine
    with engine.connect() as connection:
        definition = registered_definition(connection, config.alpha_id, config.alpha_version)
    store = PaperStore(engine, config, context)
    runtime = PaperRuntime(config, definition, context.code_commit, PostgresTripStore(engine))
    log_path, artifact = destination / "observations.jsonl", destination / "artifact.json"
    error: BaseException | None = None
    summary: dict[str, Any] | None = None
    with log_path.open("x") as log:

        def write(value: dict[str, Any]) -> None:
            log.write(json.dumps(value, allow_nan=False) + "\n")
            log.flush()

        def checkpoint() -> None:
            if (len(runtime.reports), len(runtime.snapshots), len(runtime.decisions)) != (
                store.n_reports,
                store.n_snapshots,
                store.n_decisions,
            ):
                store.save(runtime)

        def closed(bar: ClosedKline) -> None:
            write(dict(event="CLOSED", bar=bar.model_dump(mode="json")))
            runtime.closed(bar)
            checkpoint()

        def message(raw: str | bytes, received: int) -> None:
            write(
                dict(
                    event="RAW",
                    received_time=received,
                    message=raw.decode() if isinstance(raw, bytes) else raw,
                )
            )
            runtime.message(raw, received)
            checkpoint()

        def event(value: dict[str, Any]) -> None:
            write(value)
            if value["event"] in ("DISCONNECTED", "GAP", "OUT_OF_ORDER"):
                runtime.stop(
                    "feed_" + value["event"].lower(), max(runtime.clock, value["received_time"])
                )

        try:
            result = await observe_resilient_klines(
                (config.symbol,),
                config.seconds,
                closed,
                event,
                endpoint=config.endpoint,
                on_message=message,
            )
            summary = result.model_dump(mode="json")
        except BaseException as exc:
            error = exc
        finally:
            # A bounded stop also latches risk and cancels simulated pending orders.
            try:
                runtime.halt(
                    "session_failed" if error else "bounded_session_end",
                    max(runtime.clock, time.time_ns() // 1000),
                )
                checkpoint()
            except BaseException as exc:
                error = error or exc
            write(
                dict(
                    event="SESSION_END",
                    status="FAILED" if error else "FINISHED",
                    error_type=None if error is None else type(error).__name__,
                    summary=summary,
                )
            )
    payload = dict(
        version="paper_artifact_v1",
        mode="PAPER",
        is_simulated=True,
        status="FAILED" if error else "FINISHED",
        error_type=None if error is None else type(error).__name__,
        error_reason=str(error) if isinstance(error, (PaperSafetyStop, KlineStreamError)) else None,
        config=config.model_dump(mode="json"),
        experiment_id=store.experiment_id,
        context=asdict(context) | dict(created_at=context.created_at.isoformat()),
        stream_identity_sha256=sha256_file(initial),
        observations_sha256=sha256_file(log_path),
        summary=summary,
        bars=[b.model_dump(mode="json") for b in runtime.bars],
        signals=[s.model_dump(mode="json") for s in runtime.signals],
        trace=runtime.trace().model_dump(mode="json"),
        limitations=[
            "Operational integration only: the fixed minute_h04 candidate was rejected on VALID.",
            "Public last price and close marks are proxies, not bid/ask quotes or real fills.",
            "Full simulated market fills with fees/slippage; no queue, impact or borrow model.",
            "Prices strictly follow the submitted intent; no backdated opening fills.",
            "Feed failures, stale data, clock regression or expired intents stop and latch risk.",
            "No TEST, promotion, real account/order routing or restart reconciliation.",
        ],
    )
    with artifact.open("x") as handle:
        handle.write(json.dumps(payload, indent=2, allow_nan=False) + "\n")
    store.finish(artifact, sha256_file(artifact), failed=error is not None)
    if error is not None:
        raise error
    return artifact
