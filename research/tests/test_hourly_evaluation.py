from dataclasses import replace

import pytest
from sqlalchemy import text
from test_experiments import SNAPSHOT_ID
from test_experiments import registry as _registry_fixture

from helios.alpha import hourly_hypotheses, hourly_round
from helios.alpha.hourly_evaluation import hourly_requests
from helios.alpha.hourly_hypotheses import preregister_hourly
from helios.alpha.hourly_round import HOURLY_DIR, register_hourly
from helios.registry.results import Split

registry = pytest.fixture(_registry_fixture.__wrapped__)


def test_each_candidate_bound_to_own_valid_experiment_and_modified_protocol_refused(
    registry, monkeypatch, tmp_path
):
    ideas = tuple(
        replace(h, alpha_id="t_eval_" + h.alpha_id) for h in hourly_hypotheses.HOURLY_HYPOTHESES
    )
    for original, idea in zip(hourly_hypotheses.HOURLY_HYPOTHESES, ideas, strict=True):
        (tmp_path / (idea.alpha_id + ".yaml")).write_text(
            (HOURLY_DIR / (original.alpha_id + ".yaml"))
            .read_text()
            .replace(original.alpha_id, idea.alpha_id)
        )
    monkeypatch.setattr(hourly_hypotheses, "HOURLY_HYPOTHESES", ideas)
    monkeypatch.setattr(hourly_round, "HOURLY_HYPOTHESES", ideas)
    experiments = preregister_hourly(registry, SNAPSHOT_ID)
    register_hourly(registry, tmp_path)
    requests = hourly_requests(registry, tmp_path)
    assert len(requests) == 8
    assert [r.experiment_id for r in requests] == [e.experiment_id for e in experiments]
    assert all(r.split is Split.VALID and r.config.version == 1 for r in requests)
    registry.execute(
        text(
            "UPDATE experiments SET params=jsonb_set(params,'{evaluation,split}',"
            "CAST(:value AS jsonb)) "
            "WHERE experiment_id=:id"
        ),
        {"id": experiments[0].experiment_id, "value": '"test"'},
    )
    with pytest.raises(ValueError, match="VALID"):
        hourly_requests(registry, tmp_path)
