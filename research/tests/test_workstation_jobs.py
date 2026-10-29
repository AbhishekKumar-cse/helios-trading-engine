"""Durability, ownership, cancellation, source binding and bounded execution controls."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import pytest

from helios.dashboard import lab_store, lab_worker
from helios.dashboard.lab_templates import TEMPLATES, expand
from helios.dashboard.nse_backtest import DatasetChoice, NseOptions
from helios.data.equities import sha256


@pytest.fixture
def experiment(tmp_path, monkeypatch):
    directory = tmp_path / "data/equities/fixture"
    directory.mkdir(parents=True)
    (directory / "manifest.json").write_text("{}")
    code = tmp_path / "research/helios"
    code.mkdir(parents=True)
    (code / "example.py").write_text("version = 1\n")
    dataset = DatasetChoice(directory, "1h", ("EXAMPLE",), sha256(directory / "manifest.json"))
    monkeypatch.setattr(lab_store, "datasets", lambda root: [dataset])
    option = NseOptions(
        symbol="EXAMPLE",
        start=date(2026, 1, 12),
        end=date(2026, 1, 12),
        strategy="Trend following",
        lookback=1,
        expression=expand(TEMPLATES["Momentum"], "close", 1, "1h"),
    )
    return tmp_path, dataset, option


def add(experiment, **kwargs):
    root, dataset, option = experiment
    return lab_store.enqueue(
        root,
        dataset,
        [option],
        hypothesis="Frozen fixture hypothesis about continuation after costs",
        template=TEMPLATES["Momentum"],
        field="close",
        **kwargs,
    )


def test_deduplication_keeps_one_job_and_freezes_complete_context(experiment):
    root, _, option = experiment
    _, ids, reused = add(experiment)
    _, again, reused_again = add(experiment)
    assert reused == 0 and reused_again == 1 and ids == again
    rows = lab_store.jobs(root)
    assert len(rows) == 1 and rows[0]["status"] == "QUEUED"
    spec = json.loads(rows[0]["spec_json"])
    assert spec["options"] == option.model_dump(mode="json")
    assert not spec["eligible"] and spec["registry_writes"] == spec["test_accesses"] == 0
    assert len(spec["code_fingerprint"]) == 64
    assert len(list((root / "reports_out/research_lab/protocols").glob("*/protocol.json"))) == 2


def test_code_change_after_preview_is_refused_before_enqueue(experiment):
    root, _, _ = experiment
    digest = lab_store.fingerprint(root)
    (root / "research/helios/example.py").write_text("version = 2\n")
    with pytest.raises(ValueError, match="source changed"):
        add(experiment, expected_source=digest)
    assert not lab_store.jobs(root)


def test_two_workers_cannot_claim_the_same_or_another_active_slot(experiment):
    root, _, _ = experiment
    _, ids, _ = add(experiment)
    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(lambda owner: lab_store.claim(root, owner), ["one", "two"]))
    claimed = [row for row in claims if row]
    assert len(claimed) == 1 and claimed[0]["id"] == ids[0]
    assert not lab_store.pulse(root, ids[0], "not-the-owner")
    assert not lab_store.finish(root, ids[0], "not-the-owner", "COMPLETED")


def test_cancel_wins_before_completion_and_preserves_progress(experiment):
    root, _, _ = experiment
    _, ids, _ = add(experiment)
    assert lab_store.claim(root, "worker")
    assert lab_store.pulse(
        root, ids[0], "worker", progress=0.4, message="One flat session completed"
    )
    lab_store.cancel(root, ids[0])
    assert not lab_store.pulse(root, ids[0], "worker")
    assert lab_store.finish(root, ids[0], "worker", "COMPLETED", result_path="retained/receipt")
    row = lab_store.jobs(root)[0]
    assert row["status"] == "CANCELLED" and row["progress"] == 0.4
    assert row["result_path"] == "retained/receipt"
    assert lab_store.claim(root, "another") is None


def test_queued_cancel_has_no_execution_or_automatic_retry(experiment):
    root, _, _ = experiment
    _, ids, _ = add(experiment)
    lab_store.cancel(root, ids[0])
    with patch.object(lab_worker, "run_backtest", side_effect=AssertionError("execution")):
        assert lab_worker.process_one(root) is False
    assert lab_store.jobs(root)[0]["status"] == "CANCELLED"


def test_stale_recovery_revokes_owner_and_never_resumes(experiment):
    root, _, _ = experiment
    _, ids, _ = add(experiment)
    lab_store.claim(root, "old-worker")
    with lab_store.database(root) as connection:
        connection.execute(
            "UPDATE jobs SET heartbeat=? WHERE id=?",
            ((datetime.now(UTC) - timedelta(seconds=90)).isoformat(), ids[0]),
        )
        connection.commit()
    assert lab_store.interrupt_stale(root) == 1
    assert lab_store.jobs(root)[0]["status"] == "INTERRUPTED"
    assert not lab_store.pulse(root, ids[0], "old-worker")
    assert not lab_store.finish(root, ids[0], "old-worker", "COMPLETED")
    assert lab_store.claim(root, "new-worker") is None


def test_worker_refuses_changed_source_without_loading_prices(experiment):
    root, _, _ = experiment
    add(experiment)
    (root / "research/helios/example.py").write_text("version = 3\n")
    with patch.object(lab_worker, "run_backtest", side_effect=AssertionError("price access")):
        assert lab_worker.process_one(root)
    assert lab_store.jobs(root)[0]["status"] == "FAILED"


def test_both_cost_scenarios_and_finite_trial_budget_required(experiment):
    root, dataset, option = experiment
    with pytest.raises(ValueError, match="cost"):
        lab_store.enqueue(
            root,
            dataset,
            [option.model_copy(update={"compare_costs": False})],
            hypothesis="A sufficient fixture hypothesis",
            template=TEMPLATES["Momentum"],
            field="close",
        )
    with pytest.raises(ValueError, match="1–12"):
        lab_store.enqueue(
            root,
            dataset,
            [option] * 13,
            hypothesis="A sufficient fixture hypothesis",
            template=TEMPLATES["Momentum"],
            field="close",
        )
