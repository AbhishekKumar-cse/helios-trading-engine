"""Actual spawn processes demonstrate isolation/order and visible worker failures."""

import os
from dataclasses import replace

import pytest

from helios.registry.results import Split
from helios.sim.evaluate import EvaluationConfig
from helios.sim.many import EvaluationOutcome, EvaluationRequest, evaluate_many


def process_probe(request: EvaluationRequest) -> EvaluationOutcome:
    if request.alpha_id == "broken":
        raise RuntimeError("synthetic process failure")
    return EvaluationOutcome(
        request.alpha_id, request.split, str(os.getpid()), "SYNTHETIC_TEST", None
    )


def test_three_jobs_use_child_processes_and_preserve_declared_order() -> None:
    jobs = [EvaluationRequest(f"test_{i}", Split.VALID, 1, EvaluationConfig()) for i in range(3)]
    results = evaluate_many(jobs, workers=2, worker=process_probe)
    assert [r.alpha_id for r in results] == [r.alpha_id for r in jobs]
    assert all(int(r.run_id) != os.getpid() and r.error is None for r in results)


def test_worker_failure_is_not_disguised_as_a_result() -> None:
    job = EvaluationRequest("broken", Split.VALID, 1, EvaluationConfig())
    result = evaluate_many([job], workers=1, worker=process_probe)[0]
    assert result.run_id is result.status is None and result.error == "RuntimeError"
    for workers in (True, 0, 17):
        with pytest.raises(ValueError):
            evaluate_many([job], workers=workers)
    with pytest.raises(ValueError, match="duplicate"):
        evaluate_many([job, replace(job)])
