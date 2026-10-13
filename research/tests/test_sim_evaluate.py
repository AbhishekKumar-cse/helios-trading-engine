"""Composed evaluator persists real PostgreSQL rows in rolled-back fixtures."""

import hashlib
import json
import uuid
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest
from registry_sql import SNAPSHOT
from sqlalchemy import Connection, Engine, text

from helios.alpha.definition import AlphaDefinition, register_alpha_definition
from helios.common.lineage import LineageError
from helios.features.runner import FeatureFrame
from helios.registry.api import RegistryError
from helios.registry.experiments import register_experiment
from helios.registry.gates import load_gate_config_file
from helios.registry.results import Split, Status, get_result, record_result
from helios.registry.test_access import TestSetLimitReached as BudgetExhausted
from helios.registry.test_access import count_test_accesses
from helios.sim.evaluate import EvaluationConfig, EvaluationInputs, evaluate

HOUR = 3_600_000_000


@pytest.fixture
def setup(connection: Connection):
    alpha_id = "t_evaluation_alpha"
    definition = AlphaDefinition(
        alpha_id=alpha_id,
        version=1,
        name="Synthetic evaluation fixture",
        provenance="QUANT",
        feature_set_version="v1",
        horizon_family="H-HOURLY",
        horizon_periods=1,
        params={},
        expression="log_return_1",
        author="test",
    )
    register_alpha_definition(connection, definition)
    snapshot_id = "t-evaluation-snapshot"
    connection.execute(text(SNAPSHOT), {"id": snapshot_id, "commit": "a" * 40})
    load_gate_config_file(connection, author="test")
    experiment = register_experiment(
        connection,
        hypothesis="Synthetic composed evaluator verification",
        author="test",
        snapshot_id=snapshot_id,
    )
    engine = MagicMock(spec=Engine)
    engine.begin.return_value.__enter__.return_value = connection
    return engine, alpha_id, experiment.experiment_id


def inputs(window, definition):
    start = window.start_us + 24 * HOUR
    times = pd.Series([start + i * HOUR for i in range(7)])
    frame = FeatureFrame(
        "BTCUSDT",
        times,
        pd.DataFrame(
            {
                "log_return_1": [0.1, 0.2, 0.1, 0.2, 0.1, 0.2, 0.1],
                "volatility_24": [1.0, 3.0, 5.0, 1.0, 3.0, 5.0, 9.0],
            }
        ),
        pd.DataFrame(True, index=range(7), columns=["log_return_1", "volatility_24"]),
    )
    bars = pd.DataFrame(
        {"open_time": times, "close": 100 * np.cumprod([1, 1.01, 1.02, 1.01, 1.03, 1.02, 1.01])}
    )
    calibration = FeatureFrame(
        "BTCUSDT",
        pd.Series([start - (10 - i) * HOUR for i in range(6)]),
        pd.DataFrame({"volatility_24": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]}),
        pd.DataFrame({"volatility_24": [True] * 6}),
    )
    return EvaluationInputs(frame, bars, calibration, start - 10 * HOUR, start - 4 * HOUR)


def test_one_call_stores_metrics_gates_and_hash_verified_evidence(
    setup, connection: Connection, tmp_path: Path
) -> None:
    engine, alpha_id, experiment_id = setup
    result = evaluate(
        alpha_id,
        Split.VALID,
        experiment_id,
        engine=engine,
        config=EvaluationConfig(warmup_rows=0),
        load_inputs=inputs,
        output_dir=tmp_path,
        reported=False,
    )
    assert result.status is Status.EVALUATED and result.status is not Status.PROMOTED
    stored = get_result(connection, result.run_id)
    assert stored.periods == 6 and stored.evaluation_json["gate_config_hash"]
    metadata = result.evaluation_json
    artifact = Path(metadata["artifact"])
    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == metadata["artifact_sha256"]
    evidence = json.loads(artifact.read_text())
    assert len(evidence["series"]) == 7 and len(evidence["gates"]["outcomes"]) == 6
    assert evidence["mode"] == "BACKTEST" and evidence["ic"]["cross_unavailable_reason"]


def test_constant_and_data_gap_attempts_are_retained_as_invalid_without_fake_metrics(
    setup, connection: Connection, tmp_path: Path
) -> None:
    engine, alpha_id, experiment_id = setup

    def constant(window, definition):
        source = inputs(window, definition)
        source.features.values["log_return_1"] = 1.0
        return source

    result = evaluate(
        alpha_id,
        Split.VALID,
        experiment_id,
        engine=engine,
        config=EvaluationConfig(warmup_rows=0),
        load_inputs=constant,
        output_dir=tmp_path,
        reported=False,
    )
    assert result.status is Status.INVALID and result.sharpe is result.fitness is None
    assert get_result(connection, result.run_id).evaluation_json["validity"]["reasons"] == [
        "CONSTANT_ALPHA"
    ]

    def gap(window, definition):
        source = inputs(window, definition)
        keep = [0, 1, 3, 4, 5, 6]
        frame = replace(
            source.features,
            open_time=source.features.open_time.iloc[keep],
            values=source.features.values.iloc[keep],
            available=source.features.available.iloc[keep],
        )
        return replace(source, features=frame, bars=source.bars.iloc[keep])

    gapped = evaluate(
        alpha_id,
        Split.VALID,
        experiment_id,
        engine=engine,
        config=EvaluationConfig(warmup_rows=0),
        load_inputs=gap,
        output_dir=tmp_path,
        reported=False,
    )
    assert (
        gapped.status is Status.INVALID
        and "DATA_GAPS" in gapped.evaluation_json["validity"]["reasons"]
    )


def test_test_reservation_is_consumed_once_per_run_not_again_when_storing(
    setup, connection: Connection, tmp_path: Path
) -> None:
    engine, alpha_id, experiment_id = setup
    for count in (1, 2):
        result = evaluate(
            alpha_id,
            Split.TEST,
            experiment_id,
            engine=engine,
            config=EvaluationConfig(warmup_rows=0),
            load_inputs=inputs,
            output_dir=tmp_path,
            reported=False,
            actor="test",
            purpose="Synthetic final confirmation",
        )
        assert count_test_accesses(connection, alpha_id, 1) == count
        assert result.evaluation_json["test_access_id"] is not None
        if count == 1:
            with pytest.raises(RegistryError):
                with connection.begin_nested():
                    record_result(
                        connection, result.model_copy(update={"run_id": str(uuid.uuid4())})
                    )
            assert count_test_accesses(connection, alpha_id, 1) == 1
    with pytest.raises(BudgetExhausted):
        evaluate(
            alpha_id,
            Split.TEST,
            experiment_id,
            engine=engine,
            config=EvaluationConfig(warmup_rows=0),
            load_inputs=inputs,
            output_dir=tmp_path,
            reported=False,
            actor="test",
            purpose="Synthetic final confirmation",
        )


def test_reported_run_refuses_dirty_code_before_loading(setup, tmp_path: Path) -> None:
    engine, alpha_id, experiment_id = setup
    from unittest.mock import patch

    loader = MagicMock()
    with patch("helios.common.lineage.git_is_dirty", return_value=True):
        with pytest.raises(LineageError):
            evaluate(
                alpha_id,
                Split.VALID,
                experiment_id,
                engine=engine,
                load_inputs=loader,
                output_dir=tmp_path,
            )
    loader.assert_not_called()
