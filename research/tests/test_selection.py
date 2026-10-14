from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import text
from test_final_test import eligible
from test_registry_results import registry, result  # noqa: F401

from helios.registry.api import RegistryError
from helios.registry.results import Split, Status, record_result
from helios.registry.selection import get_selection, record_selection, selection_outcome


def test_valid_and_matching_test_are_both_required_for_promotion():
    valid = eligible()
    assert selection_outcome(valid, None)[0] == "REJECTED"
    test = eligible(split=Split.TEST)
    assert selection_outcome(valid, test)[0] == "PROMOTED"
    test = eligible(split=Split.TEST, fitness=Decimal(".5"))
    assert selection_outcome(valid, test)[0] == "REJECTED"


@pytest.mark.parametrize(
    "update",
    [dict(version=2), dict(snapshot_id="different-snapshot"), dict(alpha_id="another_alpha")],
)
def test_mismatched_test_cannot_confirm_a_valid_version(update):
    with pytest.raises(RegistryError, match="match"):
        selection_outcome(eligible(), eligible(split=Split.TEST).model_copy(update=update))


def test_invalid_measurement_rejected_without_inventing_a_loss():
    invalid = eligible().model_copy(update=dict(status=Status.INVALID))
    state, reasons = selection_outcome(invalid, None)
    assert state == "REJECTED" and "NO_PERFORMANCE_CONCLUSION" in reasons


def test_real_journal_is_idempotent_and_preserves_original_result(registry):  # noqa: F811
    metadata = {"status": "INVALID", "artifact_sha256": "a" * 64}
    measured = record_result(
        registry,
        result(
            status=Status.INVALID,
            sharpe=None,
            annual_return=None,
            turnover=None,
            fitness=None,
            evaluation_json=metadata,
        ),
    )
    identity = {"protocol": {"definition": {"alpha_id": measured.alpha_id, "version": 1}}}
    with patch("helios.registry.selection.verified_evidence", return_value=identity):
        one = record_selection(
            registry, round_id="fixture_round", valid_run_id=measured.run_id, actor="test"
        )
        two = record_selection(
            registry, round_id="fixture_round", valid_run_id=measured.run_id, actor="test"
        )
    assert one == two == get_selection(registry, measured.alpha_id, 1, "fixture_round")
    assert one.status == "REJECTED"
    assert (
        registry.execute(
            text("SELECT status FROM alpha_results WHERE run_id=:id"), {"id": measured.run_id}
        ).scalar_one()
        == "INVALID"
    )
    assert (
        registry.execute(
            text(
                "SELECT count(*) FROM audit_events WHERE action='ALPHA_SELECTION_DECISION' "
                "AND payload->>'round_id'='fixture_round'"
            )
        ).scalar_one()
        == 1
    )
