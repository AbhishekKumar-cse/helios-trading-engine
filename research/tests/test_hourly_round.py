import shutil
from dataclasses import replace
from pathlib import Path

import pytest
from test_experiments import SNAPSHOT_ID
from test_experiments import registry as _registry_fixture

from helios.alpha import hourly_hypotheses, hourly_round
from helios.alpha.hourly_hypotheses import preregister_hourly
from helios.alpha.hourly_round import HOURLY_DIR, load_hourly_definitions, register_hourly
from helios.registry.api import get_alpha

registry = pytest.fixture(_registry_fixture.__wrapped__)


def test_yaml_exact_plan_and_tampering_refused(tmp_path: Path):
    assert len(load_hourly_definitions()) == 8
    shutil.copytree(HOURLY_DIR, tmp_path / "hourly")
    path = tmp_path / "hourly/hourly_h01.yaml"
    path.write_text(path.read_text().replace("sign(log_return_4)", "sign(log_return_1)"))
    with pytest.raises(ValueError, match="differs"):
        load_hourly_definitions(tmp_path / "hourly")


def test_matching_preregistration_required_and_all_versions_retained(
    registry, monkeypatch, tmp_path
):
    ideas = tuple(
        replace(h, alpha_id="t_round_" + h.alpha_id) for h in hourly_hypotheses.HOURLY_HYPOTHESES
    )
    for original, idea in zip(hourly_hypotheses.HOURLY_HYPOTHESES, ideas, strict=True):
        (tmp_path / (idea.alpha_id + ".yaml")).write_text(
            (HOURLY_DIR / (original.alpha_id + ".yaml"))
            .read_text()
            .replace(original.alpha_id, idea.alpha_id)
        )
    monkeypatch.setattr(hourly_hypotheses, "HOURLY_HYPOTHESES", ideas)
    monkeypatch.setattr(hourly_round, "HOURLY_HYPOTHESES", ideas)
    with pytest.raises(ValueError, match="preregistered"):
        register_hourly(registry, tmp_path)
    preregister_hourly(registry, SNAPSHOT_ID)
    names = register_hourly(registry, tmp_path)
    assert len(names) == 8
    for name in names:
        assert get_alpha(registry, name, 1).version == 1
