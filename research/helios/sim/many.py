"""Spawn-isolated process-pool evaluation; no inherited DB engine/state (117)."""

from __future__ import annotations

import multiprocessing
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass

from helios.registry.results import Split
from helios.sim.evaluate import EvaluationConfig, evaluate


@dataclass(frozen=True)
class EvaluationRequest:
    alpha_id: str
    split: Split
    experiment_id: int
    config: EvaluationConfig
    actor: str = ""
    purpose: str = ""


@dataclass(frozen=True)
class EvaluationOutcome:
    alpha_id: str
    split: Split
    run_id: str | None
    status: str | None
    error: str | None


def _worker(request: EvaluationRequest) -> EvaluationOutcome:
    try:
        result = evaluate(
            request.alpha_id,
            request.split,
            request.experiment_id,
            config=request.config,
            actor=request.actor,
            purpose=request.purpose,
        )
        return EvaluationOutcome(
            request.alpha_id, request.split, result.run_id, result.status.value, None
        )
    except Exception as exc:
        # Do not expose SQL parameters/credentials in batch console output.
        return EvaluationOutcome(request.alpha_id, request.split, None, None, type(exc).__name__)


def evaluate_many(
    requests: Sequence[EvaluationRequest],
    *,
    workers: int = 2,
    worker: Callable[[EvaluationRequest], EvaluationOutcome] = _worker,
) -> tuple[EvaluationOutcome, ...]:
    if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1 or workers > 16:
        raise ValueError("workers must be an integer between 1 and 16")
    keys = [(r.alpha_id, r.config.version, r.split, r.config.symbol) for r in requests]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate evaluation requests would count the same attempt twice")
    if not requests:
        return ()
    results: dict[int, EvaluationOutcome] = {}
    with ProcessPoolExecutor(
        max_workers=workers, mp_context=multiprocessing.get_context("spawn")
    ) as pool:
        futures = {pool.submit(worker, request): i for i, request in enumerate(requests)}
        for future in as_completed(futures):
            i = futures[future]
            try:
                results[i] = future.result()
            except Exception as exc:
                request = requests[i]
                results[i] = EvaluationOutcome(
                    request.alpha_id, request.split, None, None, type(exc).__name__
                )
    return tuple(results[i] for i in range(len(requests)))
