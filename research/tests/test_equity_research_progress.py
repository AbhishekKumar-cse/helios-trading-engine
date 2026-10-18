"""Partial-round UI evidence must match preregistration and tolerate one in-flight append."""

import json

import pytest

from helios.dashboard.equity_research import verified_round


def test_partial_research_reads_only_complete_preregistered_outcomes(tmp_path):
    attempt = dict(symbol="EXAMPLE", candidate="momentum", experiment_id=1, alpha_id="nse_fixture")
    (tmp_path / "preregistration.json").write_text(json.dumps(dict(attempts=[attempt])))
    (tmp_path / "protocol.json").write_text(
        json.dumps(dict(test_access=False, policy=dict(interval="1m")))
    )
    path = tmp_path / "outcomes.jsonl"
    path.write_text(
        json.dumps(attempt | dict(run_id="fixture", status="REJECTED")) + '\n{"unfinished":'
    )
    result = verified_round(path)
    assert result["partial"] and len(result["results"]) == 1
    assert result["interval"] == "1m"
    path.write_text(json.dumps(attempt | dict(run_id="fixture", symbol="OTHER")) + "\n")
    with pytest.raises(ValueError, match="identity"):
        verified_round(path)
