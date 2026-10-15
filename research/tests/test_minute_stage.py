from datetime import date

import pytest
from pydantic import ValidationError

from helios.common.config import config_hash
from helios.common.project_config import (
    HorizonFamily,
    MinuteStageConfig,
    load_gates,
    load_minute_stage,
    load_splits,
)
from helios.registry.results import Split
from helios.sim.splits import split_window


def test_minute_profile_resolves_accepted_policy_and_existing_split_engine():
    stage = load_minute_stage()
    assert stage.horizon_family is HorizonFamily.MINUTE and stage.interval == "1m"
    assert stage.splits.periods_per_year == 525600
    assert stage.splits == load_splits().families[HorizonFamily.MINUTE]
    assert config_hash(stage.gates) == config_hash(load_gates())
    for split, expected_days in ((Split.TRAIN, 365), (Split.VALID, 180), (Split.TEST, 183)):
        window = split_window(split, interval=stage.interval)
        assert window.family == stage.horizon_family
        assert window.end_us - window.start_us == expected_days * 86_400_000_000
    assert stage.splits.valid.start == date(2025, 9, 2)
    assert config_hash(stage) == config_hash(load_minute_stage())


@pytest.mark.parametrize("change", ["annualization", "dates", "gates", "family", "interval"])
def test_minute_profile_refuses_cross_family_or_accepted_policy_drift(change):
    raw = load_minute_stage().model_dump(mode="json")
    if change == "annualization":
        raw["splits"]["periods_per_year"] = 8760
    elif change == "dates":
        raw["splits"] = load_splits().families[HorizonFamily.HOURLY].model_dump(mode="json")
        raw["splits"]["periods_per_year"] = 525600
    elif change == "gates":
        raw["gates"]["sharpe_min"] = 0.0
    elif change == "family":
        raw["horizon_family"] = "H-HOURLY"
    else:
        raw["interval"] = "1h"
    with pytest.raises(ValidationError):
        MinuteStageConfig.model_validate(raw)
