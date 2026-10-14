import pytest
from sqlalchemy import text
from test_experiments import SNAPSHOT_ID
from test_experiments import registry as _registry_fixture

from helios.alpha.hourly_hypotheses import HOURLY_HYPOTHESES, preregister_hourly
from helios.alpha.safety import validate_expression
from helios.features.registry import REGISTRY

registry = pytest.fixture(_registry_fixture.__wrapped__)


def test_eight_fixed_semantically_valid_definitions():
    assert len(HOURLY_HYPOTHESES) == len({h.alpha_id for h in HOURLY_HYPOTHESES}) == 8
    for candidate in HOURLY_HYPOTHESES:
        definition = candidate.definition()
        validate_expression(
            definition.expression, feature_names=REGISTRY.names(), params={}, interval="1h"
        )
        assert definition.version == 1 and len(candidate.hypothesis) > 10


def test_preregister_all_before_results_and_refuse_duplicates(registry):
    rows = preregister_hourly(registry, SNAPSHOT_ID)
    assert len(rows) == 8
    assert all(row.pre_registered_at and row.params["test_access"] is False for row in rows)
    assert (
        registry.execute(
            text("SELECT count(*) FROM alpha_results WHERE experiment_id = ANY(:ids)"),
            {"ids": [r.experiment_id for r in rows]},
        ).scalar_one()
        == 0
    )
    with pytest.raises(ValueError, match="already"):
        preregister_hourly(registry, SNAPSHOT_ID)
