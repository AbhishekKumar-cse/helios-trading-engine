from decimal import Decimal

import pytest
from test_registry_results import result

from helios.alpha.search_effort import comparison
from helios.registry.results import Split, Status


def invalid(**updates):
    return result().model_copy(
        update=dict(status=Status.INVALID, sharpe=None, fitness=None, **updates)
    )


def test_invalid_attempts_count_but_never_rank_as_best():
    rows = [invalid(run_id="one"), invalid(run_id="two", split=Split.TRAIN)]
    summary = comparison(rows)
    assert summary["n_attempts"] == summary["n_invalid"] == 2
    assert summary["n_valid_attempts"] == 1
    assert summary["best_run_id"] is summary["best_fitness"] is None


def test_ranking_uses_only_clean_valid_measurements_not_train_or_dirty():
    rows = [
        result().model_copy(update=dict(run_id="valid", split=Split.VALID, fitness=Decimal(2))),
        result().model_copy(update=dict(run_id="train", split=Split.TRAIN, fitness=Decimal(100))),
        result().model_copy(
            update=dict(run_id="dirty", split=Split.VALID, dirty=True, fitness=Decimal(200))
        ),
    ]
    assert comparison(rows)["best_run_id"] == "valid"


def test_duplicate_attempt_cannot_inflate_search_effort():
    with pytest.raises(ValueError, match="twice"):
        same = result()
        comparison([same, same])
