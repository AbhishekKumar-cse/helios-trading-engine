"""Synthetic frozen ML fixtures; SQL rows roll back and never claim market results."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest
from registry_sql import SNAPSHOT
from sqlalchemy import Engine, text
from test_prediction_alpha import fixture
from test_sim_evaluate import inputs

from helios.alpha.definition import register_alpha_definition
from helios.common.config import config_hash
from helios.common.project_config import HorizonFamily
from helios.common.types import AlphaStatus
from helios.data.binance import sha256_file
from helios.data.klines import interval_us
from helios.ml.dataset import DatasetConfig, DatasetError
from helios.ml.prediction_alpha import prediction_to_alpha
from helios.ml.registered_alpha import (
    frozen_definition,
    frozen_ml_series,
    ml_evaluation_protocol,
    read_frozen_ml,
)
from helios.registry.api import Provenance, get_alpha
from helios.registry.experiments import ExperimentKind, register_experiment
from helios.registry.gates import load_gate_config_file
from helios.registry.results import Split, Status, get_result
from helios.registry.test_access import count_test_accesses
from helios.sim.evaluate import EvaluationConfig, evaluate
from helios.sim.splits import split_window


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True) + "\n")


def artifact_fixture(tmp_path, split=Split.VALID, interval="1h"):
    policy, lineage, predictions = fixture(
        ready=split_window(Split.VALID, interval=interval).end_us
    )
    window = split_window(split, interval=interval)
    source_inputs = inputs(window, None)
    if interval == "1m":
        source_inputs.features.open_time[:] = pd.Series(
            [window.start_us + (24 + i) * interval_us(interval) for i in range(7)]
        )
    predictions = predictions.iloc[:7].copy()
    predictions["open_time"] = source_inputs.features.open_time
    model = tmp_path / "model"
    calibration = tmp_path / "calibration"
    artifact = tmp_path / "alpha"
    for folder in (model, calibration, artifact):
        folder.mkdir()
    (model / "lightgbm.joblib").write_bytes(b"synthetic fixture; never unpickled")
    predictions.to_parquet(model / "valid_predictions.parquet", index=False)
    snapshot = "t-ml-evaluation-snapshot"
    base_lineage = dict(
        code_commit="a" * 40, config_hash="b" * 64, data_snapshot_id=snapshot, dirty=False, seed=0
    )
    dataset = DatasetConfig(features=("log_return_1",), interval=interval)
    write_json(
        model / "metrics.json",
        dict(
            protocol=dict(
                version="minute_lightgbm_v1" if interval == "1m" else "hourly_lightgbm_v1",
                test_access=False,
                config=dict(dataset=dataset.model_dump(mode="json")),
            ),
            lineage=base_lineage,
            artifact_hashes={
                name: sha256_file(model / name)
                for name in ("lightgbm.joblib", "valid_predictions.parquet")
            },
        ),
    )
    frozen = policy.calibration.model_copy(
        update=dict(
            model_sha256=sha256_file(model / "lightgbm.joblib"),
            snapshot_id=snapshot,
            source_metrics_sha256=sha256_file(model / "metrics.json"),
        )
    )
    (calibration / "isotonic.json").write_text(frozen.model_dump_json())
    for name in ("valid_diagnostics.parquet", "calibration.svg"):
        (calibration / name).write_bytes(b"synthetic diagnostic fixture")
    write_json(
        calibration / "metrics.json",
        dict(
            source=str(model / "metrics.json"),
            map=frozen.model_dump(mode="json"),
            protocol=dict(test_access=False),
            lineage=base_lineage,
            artifact_hashes={
                name: sha256_file(calibration / name)
                for name in ("isotonic.json", "valid_diagnostics.parquet", "calibration.svg")
            },
        ),
    )
    policy = policy.model_copy(
        update=dict(
            calibration=frozen,
            payoffs=policy.payoffs.model_copy(
                update=dict(
                    snapshot_id=snapshot,
                    available_after_us=split_window(Split.TRAIN, interval=interval).end_us,
                )
            ),
        )
    )
    lineage = lineage.model_copy(
        update=dict(
            alpha_id="t_ml_evaluation",
            snapshot_id=snapshot,
            code_commit="a" * 40,
            config_hash=config_hash(policy),
            model_hash=frozen.model_sha256,
            horizon_family=HorizonFamily.MINUTE if interval == "1m" else HorizonFamily.HOURLY,
        )
    )
    output = prediction_to_alpha(predictions, policy, lineage)
    (artifact / "policy.json").write_text(policy.model_dump_json())
    output.diagnostics.to_parquet(artifact / "diagnostics.parquet", index=False)
    (artifact / "alpha_values.jsonl").write_text(
        "".join(v.model_dump_json() + "\n" for v in output.values)
    )
    write_json(
        artifact / "metrics.json",
        dict(
            calibration=str(calibration / "metrics.json"),
            n_rows=len(output.values),
            n_available=sum(v.status is AlphaStatus.OK for v in output.values),
            protocol=dict(
                calibration_metrics_sha256=sha256_file(calibration / "metrics.json"),
                test_access=False,
                post_calibration_only=True,
                window=3,
                cost_sides=2,
            ),
            lineage=base_lineage | dict(config_hash=config_hash(policy)),
            artifact_hashes={
                name: sha256_file(artifact / name)
                for name in ("policy.json", "alpha_values.jsonl", "diagnostics.parquet")
            },
        ),
    )
    return artifact / "metrics.json"


def test_frozen_availability_mapping_and_immutable_model_reference(tmp_path):
    path = artifact_fixture(tmp_path)
    artifact = read_frozen_ml(path)
    definition = frozen_definition(artifact)
    alpha, evidence = frozen_ml_series(
        definition,
        split_window(Split.VALID, interval="1h"),
        symbol="BTCUSDT",
        snapshot_id=artifact.policy.calibration.snapshot_id,
    )
    assert not alpha.available.any() and alpha.values.isna().all()
    assert alpha.open_time.iloc[0] == artifact.values[0].timestamp - 3_600_000_000
    assert evidence["model_ref"] == definition.model_ref
    assert ml_evaluation_protocol(artifact)["test_access"] is False
    path.write_text(path.read_text() + " ")
    with pytest.raises(DatasetError, match="reference"):
        read_frozen_ml(path, definition.model_ref)


@pytest.mark.parametrize(
    "file",
    [
        "alpha/alpha_values.jsonl",
        "alpha/policy.json",
        "model/lightgbm.joblib",
        "calibration/isotonic.json",
    ],
)
def test_artifact_tampering_fails_closed(tmp_path, file):
    path = artifact_fixture(tmp_path)
    (tmp_path / file).write_bytes(b"changed")
    with pytest.raises(DatasetError, match="hash|checksum"):
        read_frozen_ml(path)


def test_train_evaluation_refused_before_reading_valid_artifacts(tmp_path):
    artifact = read_frozen_ml(artifact_fixture(tmp_path))
    definition = frozen_definition(artifact)
    artifact.path.unlink()
    with pytest.raises(DatasetError, match="TRAIN"):
        frozen_ml_series(
            definition,
            split_window(Split.TRAIN, interval="1h"),
            symbol="BTCUSDT",
            snapshot_id=artifact.policy.calibration.snapshot_id,
        )


@pytest.mark.parametrize("split", [Split.VALID, Split.TEST])
def test_ml_rows_use_common_simulator_and_all_gates(connection, tmp_path, split):
    artifact = read_frozen_ml(artifact_fixture(tmp_path, split))
    definition = frozen_definition(artifact)
    register_alpha_definition(connection, definition)
    snapshot = artifact.policy.calibration.snapshot_id
    connection.execute(text(SNAPSHOT), {"id": snapshot, "commit": "a" * 40})
    load_gate_config_file(connection, author="test")
    experiment = register_experiment(
        connection,
        hypothesis="Synthetic frozen ML evaluation fixture",
        kind=ExperimentKind.ML,
        author="test",
        snapshot_id=snapshot,
    )
    engine = MagicMock(spec=Engine)
    engine.begin.return_value.__enter__.return_value = connection
    result = evaluate(
        definition.alpha_id,
        split,
        experiment.experiment_id,
        engine=engine,
        config=EvaluationConfig(warmup_rows=2),
        load_inputs=inputs,
        output_dir=tmp_path / "results",
        reported=False,
        actor="test",
        purpose="Synthetic frozen ML counter fixture",
    )
    stored = get_result(connection, result.run_id)
    assert get_alpha(connection, definition.alpha_id).provenance is Provenance.ML
    assert set(stored.gate_results) == {"G1", "G2", "G3", "G4", "G5", "G6"}
    assert count_test_accesses(connection, definition.alpha_id, 1) == (split is Split.TEST)
    if split is Split.VALID:
        assert stored.status is Status.INVALID and stored.sharpe is stored.fitness is None
        assert "UNAVAILABLE_AFTER_WARMUP" in stored.evaluation_json["validity"]["reasons"]
    else:
        assert stored.status is Status.REJECTED and stored.periods == 4
        evidence = json.loads(Path(stored.evaluation_json["artifact"]).read_text())
        assert evidence["costs"] and evidence["fitness"] and evidence["ic"]
        assert evidence["feature_provenance"]["ml"]["model_ref"] == definition.model_ref
