"""Explicit synthetic fixtures for the shared NSE research adapter."""

from dataclasses import replace
from decimal import Decimal, localcontext
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest
from registry_sql import SNAPSHOT
from sqlalchemy import Engine, text

from helios.alpha.definition import AlphaDefinition, register_alpha_definition
from helios.alpha.evaluator import AlphaSeries
from helios.alpha.output import bound_alpha
from helios.backtest.equity import eligible_sessions, replay_session
from helios.common.config import config_hash, load_config
from helios.common.project_config import GatesConfig
from helios.common.types import Bar
from helios.equities.config import EquityResearchPolicy
from helios.equities.inputs import EquityInputs
from helios.equities.model import fit_equity_model
from helios.equities.pipeline import candidate_definition
from helios.features.runner import FeatureFrame
from helios.ml.equity_pilot import features_and_labels, features_for
from helios.registry.api import RegistryError
from helios.registry.experiments import register_experiment
from helios.registry.gates import store_gate_config
from helios.registry.results import Split, Status, get_result
from helios.sim.equity_evaluation import GATES_PATH, EquityEvaluationContext
from helios.sim.evaluate import evaluate
from helios.sim.report import generate_report


def fixture_inputs(symbol="EXAMPLE", start="2026-01-09", days=35):
    dates = pd.bdate_range(start, periods=days, tz="Asia/Kolkata")
    parts = []
    for slot in range(7):
        times = dates + pd.Timedelta(hours=9, minutes=15) + pd.Timedelta(hours=slot)
        opening = 100 + np.arange(days) * 0.01 + np.sin(np.arange(days) + slot) * 0.3
        close = opening * (1 + np.sin(np.arange(days) * 0.7 + slot) * 0.003)
        parts.append(
            pd.DataFrame(
                dict(
                    symbol=symbol,
                    timestamp=times.tz_convert("UTC"),
                    open_time=times.as_unit("us").astype("int64"),
                    session_date=dates.strftime("%Y-%m-%d"),
                    available_at=(times + pd.Timedelta(minutes=60 if slot < 6 else 15)).tz_convert(
                        "UTC"
                    ),
                    open=opening,
                    high=np.maximum(opening, close) + 1,
                    low=np.minimum(opening, close) - 1,
                    close=close,
                    adjusted_close=close,
                    volume=10000.0,
                    full_bar=slot < 6,
                )
            )
        )
    bars = pd.concat(parts).sort_values("open_time").reset_index(drop=True)
    samples = features_and_labels(bars, "60m", include_unlabelled=True)
    columns = list(features_for("60m"))
    available = pd.DataFrame({name: samples.feature_available for name in columns})
    frame = FeatureFrame(
        symbol,
        samples.timestamp.dt.as_unit("us").astype("int64"),
        samples[columns].where(available),
        available,
    )
    return EquityInputs(symbol, bars, frame, tuple(dates.strftime("%Y-%m-%d")), {})


def fixture_alpha(inputs):
    return bound_alpha(
        AlphaSeries(
            inputs.symbol,
            inputs.features.open_time,
            (inputs.features.values.return_1 > 0)
            .astype(float)
            .where(inputs.features.available.return_1),
            inputs.features.available.return_1.copy(),
        )
    )


def test_production_candidate_metadata_does_not_break_formula_evaluation():
    from helios.alpha.output import evaluate_definition

    model = MagicMock()
    model.model_hash, model.calibration_hash = "e" * 64, "f" * 64
    inputs = fixture_inputs(days=3)
    for name in ("momentum", "reversal"):
        stored = candidate_definition("nse_fixture", name, model)
        assert stored.spec["market"] == "nse_cash" and stored.spec["params"] == {}
        definition = AlphaDefinition(
            alpha_id=stored.alpha_id,
            name=stored.name,
            provenance="QUANT",
            version=1,
            feature_set_version=stored.feature_set_version,
            horizon_family=stored.horizon_family,
            horizon_periods=1,
            expression=stored.spec["expression"],
            author="test",
        )
        assert evaluate_definition(definition, inputs.features, interval="1h").available.any()


def test_normal_nse_clock_and_partial_hour_require_explicit_market():
    frame = fixture_inputs(days=1).bars
    first = frame.iloc[0]
    bar = Bar(
        symbol="EXAMPLE",
        source="synthetic_test",
        sequence=0,
        interval="1h",
        open_time=int(first.open_time),
        ingest_time=int(first.open_time) + 3600000000,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=Decimal("10"),
        snapshot_id="a" * 64,
    )
    assert not bar.is_complete_interval
    assert bar.model_copy(update={"calendar": "nse_regular_v1"}).is_complete_interval
    final = bar.model_copy(
        update={
            "calendar": "nse_regular_v1",
            "open_time": int(frame.open_time.iloc[-1]),
            "recorded_close_time": int(frame.open_time.iloc[-1]) + 900000000 - 1,
            "ingest_time": int(frame.open_time.iloc[-1]) + 900000000,
        }
    )
    assert final.is_complete_interval
    assert not final.model_copy(
        update={"recorded_close_time": final.open_time + 3600000000 - 1}
    ).is_complete_interval


@pytest.mark.leakage
def test_feature_availability_is_independent_of_future_label_availability():
    frame = fixture_inputs(days=3).bars
    before = features_and_labels(frame, "60m", include_unlabelled=True)
    cutoff = frame.timestamp.iloc[11]
    frame.loc[frame.timestamp >= cutoff, ["open", "high", "low", "close", "volume"]] = np.nan
    after = features_and_labels(frame, "60m", include_unlabelled=True)
    columns = [*features_for("60m"), "feature_available"]
    pd.testing.assert_frame_equal(
        before.loc[before.timestamp < cutoff, columns], after.loc[after.timestamp < cutoff, columns]
    )


def test_shared_replay_uses_whole_shares_inr_real_openings_and_finishes_flat():
    inputs = fixture_inputs(days=2)
    frame = inputs.bars.iloc[7:].reset_index(drop=True)
    # A fixed synthetic test target is available before the entry opening.
    alpha = bound_alpha(
        AlphaSeries(
            inputs.symbol,
            inputs.features.open_time,
            pd.Series(np.ones(inputs.features.rows)),
            pd.Series(True, index=range(inputs.features.rows)),
        )
    )
    result = replay_session(
        frame,
        alpha,
        EquityResearchPolicy(),
        snapshot_id="a" * 64,
        alpha_id="nse_test",
        code_commit="b" * 40,
    )
    assert result.n_fills >= 2
    assert result.trace.positions[-1].quantity == 0 and not result.trace.tail
    openings = {int(row.open_time): Decimal(str(row.open)) for row in frame.itertuples()}
    cash = Decimal("100000")
    with localcontext() as context:
        context.prec = 100
        for report in result.trace.reports:
            if report.fill is None:
                continue
            fill = report.fill
            sign = 1 if fill.side.value == "BUY" else -1
            assert fill.fee_asset == "INR" and fill.quantity == fill.quantity.to_integral_value()
            assert abs(
                fill.price - openings[fill.timestamp] * (1 + sign * Decimal(".0005"))
            ) <= Decimal("1e-18")
            assert abs(fill.fee - fill.quantity * fill.price * Decimal(".0015")) <= Decimal("1e-18")
            cash -= sign * fill.quantity * fill.price + fill.fee
        assert abs(cash - result.trace.snapshots[-1].equity) < Decimal("1e-15")


def test_incomplete_sessions_are_counted_and_never_filled():
    inputs = fixture_inputs(days=3)
    broken = replace(inputs, bars=inputs.bars.drop(index=[10]).reset_index(drop=True))
    sessions, excluded = eligible_sessions(broken)
    assert len(sessions) == 2 and len(excluded) == 1
    assert excluded[0]["reason"] == "missing_or_nonstandard_bar_slots"


def test_session_fill_ids_are_unique_when_execution_evidence_is_combined():
    inputs = fixture_inputs(days=4)
    alpha = fixture_alpha(inputs)
    fill_ids = []
    for _, frame in inputs.bars.groupby("session_date"):
        result = replay_session(
            frame.reset_index(drop=True),
            alpha,
            EquityResearchPolicy(),
            snapshot_id="a" * 64,
            alpha_id="nse_test",
            code_commit="b" * 40,
        )
        fill_ids.extend(fill["fill_id"] for fill in result.fills)
    assert len(fill_ids) >= 4
    assert len(fill_ids) == len(set(fill_ids))


@pytest.mark.leakage
def test_equity_test_is_rejected_before_db_or_data_access(tmp_path):
    engine = MagicMock(spec=Engine)
    with pytest.raises(RegistryError, match="TEST stays sealed"):
        evaluate(
            "nse_test",
            Split.TEST,
            1,
            engine=engine,
            equity=MagicMock(),
            output_dir=tmp_path,
            reported=False,
        )
    engine.begin.assert_not_called()


@pytest.mark.leakage
def test_ml_fit_and_calibration_do_not_change_when_valid_prices_change(tmp_path):
    inputs = [fixture_inputs(symbol, "2024-10-21", 400) for symbol in ("EXAMPLE", "EXAMPLE2")]
    model, first = fit_equity_model(inputs, EquityResearchPolicy(), tmp_path / "first")
    for item in inputs:
        future = item.bars.session_date >= "2026-01-09"
        item.bars.loc[future, ["open", "high", "low", "close", "adjusted_close"]] *= 7
    repeated, second = fit_equity_model(inputs, EquityResearchPolicy(), tmp_path / "second")
    assert model.model_hash == repeated.model_hash
    assert first == second and model.calibration_hash == repeated.calibration_hash
    assert first["train_last_label"] < first["calibration_first_feature"]
    assert first["calibration_last_label"].startswith("2025-12-31")


def test_shared_evaluator_records_equity_results_and_reports(connection, tmp_path):
    policy = EquityResearchPolicy()
    inputs = fixture_inputs()
    definition = AlphaDefinition(
        alpha_id="nse_t_research",
        version=1,
        name="Synthetic NSE fixture",
        provenance="QUANT",
        feature_set_version="nse_session_features_v1",
        horizon_family="H-HOURLY",
        horizon_periods=1,
        expression="clip(sign(return_1),0,1)",
        author="test",
    )
    register_alpha_definition(connection, definition)
    connection.execute(text(SNAPSHOT), {"id": "c" * 64, "commit": "a" * 40})
    store_gate_config(connection, load_config(GATES_PATH, GatesConfig), author="test")
    model = MagicMock()
    model.model_hash, model.calibration_hash = "e" * 64, "f" * 64
    parameters = dict(
        market="nse_cash",
        symbol=inputs.symbol,
        alpha_id=definition.alpha_id,
        policy_hash=config_hash(policy),
        model_hash=model.model_hash,
        calibration_hash=model.calibration_hash,
        source_hashes={},
    )
    experiment = register_experiment(
        connection,
        hypothesis="Synthetic equity integration verification",
        params=parameters,
        author="test",
        snapshot_id="c" * 64,
    )
    engine = MagicMock(spec=Engine)
    engine.begin.return_value.__enter__.return_value = connection
    result = evaluate(
        definition.alpha_id,
        Split.VALID,
        experiment.experiment_id,
        engine=engine,
        equity=EquityEvaluationContext(policy, inputs, "c" * 64, model, {}),
        output_dir=tmp_path,
        reported=False,
    )
    assert result.status is Status.REJECTED and not result.gate_results["G7"]
    stored = get_result(connection, result.run_id)
    assert result.periods == 35
    assert stored == result, {
        key: (value, stored.model_dump()[key])
        for key, value in result.model_dump().items()
        if value != stored.model_dump()[key]
    }
    path = generate_report(result, output_root=tmp_path / "html")
    assert "NSE conditional" in Path(path).read_text()
    with pytest.raises(RegistryError, match="already has a result"):
        evaluate(
            definition.alpha_id,
            Split.VALID,
            experiment.experiment_id,
            engine=engine,
            equity=EquityEvaluationContext(policy, inputs, "c" * 64, model, {}),
            output_dir=tmp_path,
            reported=False,
        )
