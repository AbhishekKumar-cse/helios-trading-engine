import json
from dataclasses import replace
from unittest.mock import MagicMock

import pytest
from registry_sql import SNAPSHOT
from sqlalchemy import Engine, text
from test_ml_dataset import fixture
from test_sim_evaluate import inputs

from helios.alpha import minute_round
from helios.alpha.definition import AlphaDefinition, register_alpha_definition
from helios.alpha.minute_round import minute_definitions, minute_protocol
from helios.common.project_config import HorizonFamily
from helios.ml.dataset import DatasetConfig, build_dataset
from helios.registry.experiments import ExperimentStatus, register_experiment, set_status
from helios.registry.gates import load_gate_config_file
from helios.registry.results import Split
from helios.sim.evaluate import EvaluationConfig, evaluate


def test_minute_dataset_labels_follow_minutes_not_hours():
    frame, bars = fixture()
    frame = replace(frame, open_time=frame.open_time // 60)
    bars.open_time //= 60
    result = build_dataset(
        {"BTCUSDT": frame},
        {"BTCUSDT": bars},
        config=DatasetConfig(interval="1m", features=("momentum",), horizon=2),
    )
    assert len(result.samples) == 3
    assert all(s.label_end_time - s.open_time == 120_000_000 for s in result.samples)


def test_fixed_minute_protocol_has_three_baselines_eight_candidates_and_no_test():
    definitions = minute_definitions()
    assert len(definitions) == len({d.alpha_id for d in definitions}) == 11
    assert all(d.horizon_family is HorizonFamily.MINUTE for d in definitions)
    assert all(minute_protocol(d)["evaluation"]["interval"] == "1m" for d in definitions)
    assert all(minute_protocol(d)["test_access"] is False for d in definitions)


def test_minute_registration_requires_exact_unconsumed_preregistration(connection, monkeypatch):
    frozen = tuple(
        d.model_copy(update={"alpha_id": "test_" + d.alpha_id}) for d in minute_definitions()
    )
    monkeypatch.setattr(minute_round, "AUTHOR", "test_minute_round")
    monkeypatch.setattr(minute_round, "minute_definitions", lambda: frozen)
    connection.execute(
        text(SNAPSHOT.replace("'1h'", "'1m'")), {"id": "test-minute-round", "commit": "a" * 40}
    )
    ids = minute_round.preregister_minute(connection, "test-minute-round")
    assert len(ids) == 11
    with pytest.raises(ValueError, match="already preregistered"):
        minute_round.preregister_minute(connection, "test-minute-round")
    requests = minute_round.minute_requests(connection, register=True)
    assert len(requests) == 11 and all(r.split is Split.VALID for r in requests)
    assert minute_round.minute_requests(connection) == requests
    set_status(connection, ids[0], ExperimentStatus.RUNNING)
    with pytest.raises(ValueError, match="preregistration"):
        minute_round.minute_requests(connection)


def test_same_composed_evaluator_uses_minute_metrics_and_regime_grid(connection, tmp_path):
    d = AlphaDefinition(
        alpha_id="test_minute_eval",
        version=1,
        name="Minute fixture",
        provenance="QUANT",
        feature_set_version="v1",
        horizon_family="H-MINUTE",
        horizon_periods=1,
        expression="log_return_1",
        author="test",
    )
    register_alpha_definition(connection, d)
    connection.execute(
        text(SNAPSHOT.replace("'1h'", "'1m'")), {"id": "test-minute-eval", "commit": "a" * 40}
    )
    load_gate_config_file(connection, author="test")
    e = register_experiment(
        connection,
        hypothesis="Minute composed evaluator fixture",
        author="test",
        snapshot_id="test-minute-eval",
    )
    engine = MagicMock(spec=Engine)
    engine.begin.return_value.__enter__.return_value = connection

    def minute_inputs(window, definition):
        source = inputs(window, definition)

        def convert(t):
            return window.start_us + (t - window.start_us) // 60

        return replace(
            source,
            features=replace(source.features, open_time=convert(source.features.open_time)),
            bars=source.bars.assign(open_time=convert(source.bars.open_time)),
            calibration=replace(
                source.calibration, open_time=convert(source.calibration.open_time)
            ),
            calibration_start_us=convert(source.calibration_start_us),
            calibration_end_us=convert(source.calibration_end_us),
        )

    result = evaluate(
        d.alpha_id,
        Split.VALID,
        e.experiment_id,
        engine=engine,
        config=EvaluationConfig(interval="1m", warmup_rows=0),
        load_inputs=minute_inputs,
        output_dir=tmp_path,
        reported=False,
    )
    evidence = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert result.periods == 6
    assert evidence["diagnostics"]["base"]["config"]["periods_per_year"] == 525600
    assert evidence["stability"]["regime_fit"]["config"]["interval"] == "1m"
