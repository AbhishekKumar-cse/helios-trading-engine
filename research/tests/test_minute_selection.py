import hashlib
import json
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from test_final_test import eligible

from helios.alpha.minute_selection import (
    MINUTE_CANDIDATES,
    reject_ineligible_minute,
    review_minute,
)
from helios.common.project_config import HorizonFamily
from helios.registry.results import Status


@pytest.fixture
def minute_review():
    evidence, rows = {}, {}
    for name in MINUTE_CANDIDATES:
        row = eligible(alpha_id=name)
        protocol = dict(
            definition=dict(alpha_id=name, version=1, horizon_family="H-MINUTE"), split="valid"
        )
        row = row.model_copy(
            update=dict(
                status=Status.REJECTED,
                gate_results={f"G{i}": i != 1 for i in range(1, 7)},
                config_hash=hashlib.sha256(
                    json.dumps(protocol, sort_keys=True).encode()
                ).hexdigest(),
                evaluation_json=(row.evaluation_json or {}) | dict(artifact_sha256="a" * 64),
            )
        )
        rows[name] = row
        evidence[name] = dict(
            protocol=protocol, source=dict(commit=row.code_commit, dirty=False, seed=row.seed)
        )
    connection = MagicMock()
    connection.execute.return_value.scalar_one.return_value = 1
    with ExitStack() as stack:
        for name, value in dict(
            get_alpha=lambda *_: SimpleNamespace(version=1, horizon_family=HorizonFamily.MINUTE),
            list_results=lambda _, **kw: [rows[kw["alpha_id"]]],
            verified_evidence=lambda row: evidence[row.alpha_id],
            count_test_accesses=lambda *_: 0,
        ).items():
            stack.enter_context(patch("helios.alpha.minute_selection." + name, side_effect=value))
        yield connection, rows, evidence


@pytest.mark.leakage
def test_failed_minute_gates_do_not_create_a_test_shortlist(minute_review):
    connection, _, _ = minute_review
    review = review_minute(connection)
    assert review["decision"] == "SKIPPED_NO_ELIGIBLE_CANDIDATES"
    assert review["selected"] == [] and len(review["reviewed"]) == 12
    assert all("INCOMPLETE_OR_FAILED_GATES" in r["reasons"] for r in review["reviewed"])


def test_minute_review_verifies_source_before_any_decision(minute_review):
    connection, _, evidence = minute_review
    evidence[MINUTE_CANDIDATES[0]]["source"]["dirty"] = True
    with pytest.raises(ValueError, match="lineage mismatch"):
        review_minute(connection)


def test_skip_rejects_changed_review_before_writing_decisions(minute_review):
    connection, _, _ = minute_review
    review = review_minute(connection)
    review["selected"] = [dict(alpha_id="invented_winner")]
    with patch("helios.alpha.minute_selection.record_selection") as record:
        with pytest.raises(ValueError, match="unchanged"):
            reject_ineligible_minute(connection, review)
        record.assert_not_called()
