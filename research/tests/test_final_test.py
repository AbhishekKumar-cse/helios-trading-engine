from decimal import Decimal

import pytest
from test_registry_results import result

from helios.alpha.final_test import eligibility, rank_shortlist
from helios.common.config import config_hash
from helios.common.project_config import load_gates
from helios.registry.results import Split, Status


def eligible(**updates):
    return result(
        stability_positive_fraction=Decimal(".8"),
        cost_stress_sharpe=Decimal("1"),
        evaluation_json={"gate_config_hash": config_hash(load_gates())},
        gate_config_id=load_gates().version,
        **updates,
    )


@pytest.mark.leakage
def test_invalid_round_has_no_test_shortlist():
    invalid = eligible().model_copy(update=dict(status=Status.INVALID, sharpe=None, fitness=None))
    assert rank_shortlist([invalid]) == ()


@pytest.mark.parametrize(
    "change",
    [
        dict(split=Split.TRAIN),
        dict(dirty=True),
        dict(gate_results={"G1": True}),
        dict(fitness=Decimal(".9")),
        dict(evaluation_json={"gate_config_hash": "f" * 64}),
    ],
)
def test_promotion_preconditions_cannot_be_bypassed(change):
    assert eligibility(eligible().model_copy(update=change))


def test_frozen_ranking_limits_candidates_and_uses_valid_fitness():
    rows = [eligible(alpha_id=f"test_a{i}", fitness=Decimal(i + 2)) for i in range(5)]
    assert [s.alpha_id for s in rank_shortlist(rows)] == ["test_a4", "test_a3"]
    assert len(rank_shortlist(rows, 3)) == 3
    with pytest.raises(ValueError):
        rank_shortlist(rows, 4)
    with pytest.raises(ValueError, match="one frozen"):
        rank_shortlist([rows[0], rows[0]])
