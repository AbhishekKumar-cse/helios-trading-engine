"""Causal history and actual shared-engine fixed-share execution checks."""

from dataclasses import replace
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest
from test_equity_rebuild import policy
from test_equity_rebuild import reviewed_frame as source_frame

from helios.alpha.evaluator import AlphaSeries
from helios.alpha.output import bound_alpha
from helios.backtest.equity import replay_session
from helios.equities.charges import ChargeTrade, estimate_intraday_charges
from helios.equities.inputs import EquityInputs
from helios.equities.paper_features import causal_setups, feature_digest, signal_frame
from helios.equities.paper_signals import Setup
from helios.features.runner import FeatureFrame


def reviewed_frame(day):
    return source_frame(day).astype({c: float for c in ("open", "high", "low", "close")})


def target(frame, entry=29, exit_=89):
    values = pd.Series(0.0, index=frame.index)
    values.iloc[entry:exit_] = 1.0
    return bound_alpha(
        AlphaSeries("EXAMPLE", frame.open_time, values, pd.Series(True, index=frame.index))
    )


def run(frame, alpha, multiplier=1):
    return replay_session(
        frame,
        alpha,
        policy(),
        snapshot_id="a" * 64,
        alpha_id="nse_paper_fixture",
        code_commit="b" * 40,
        multiplier=multiplier,
        state_changes_only=True,
        feature_set_version="nse_paper_minute_features_v1",
    )


def test_state_changes_preserve_actual_shares_and_use_next_open_with_exact_fees():
    frame = reviewed_frame("2026-01-09")
    frame.loc[30:88, ["open", "close"]] = 105.0
    frame["high"] = 106.0
    alpha = target(frame)
    first, stress = run(frame, alpha), run(frame, alpha, 2)
    assert first.n_fills == stress.n_fills == 2
    buy, sell = first.fills
    assert buy["side"] == "BUY" and sell["side"] == "SELL"
    assert Decimal(buy["quantity"]) == Decimal(sell["quantity"]) == 500
    assert buy["timestamp"] == int(frame.open_time.iloc[30])
    assert sell["timestamp"] == int(frame.open_time.iloc[90])
    assert Decimal(buy["price"]) == Decimal("105.0525")
    assert Decimal(sell["price"]) == Decimal("99.9500")
    trades = [
        ChargeTrade(
            pd.Timestamp(first.day).date(),
            "EXAMPLE",
            str(i),
            f["side"],
            Decimal(f["quantity"]),
            Decimal(f["price"]),
        )
        for i, f in enumerate(first.fills)
    ]
    assert Decimal(first.fees) == estimate_intraday_charges(trades).total
    assert first.trace.positions[-1].quantity == 0
    assert stress.net_return < first.net_return
    assert all(p.quantity >= 0 for p in first.trace.positions)


@pytest.mark.leakage
def test_future_exit_prices_do_not_change_fixed_entry_quantity_or_fee():
    frame = reviewed_frame("2026-01-09")
    future = frame.copy()
    future.loc[60:, ["open", "high", "low", "close"]] *= 1.01
    first, second = run(frame, target(frame)), run(future, target(future))
    assert first.fills[0]["quantity"] == second.fills[0]["quantity"]
    assert first.fills[0]["fee"] == second.fills[0]["fee"]
    assert first.fills[0]["price"] == second.fills[0]["price"]


def history_fixture():
    days = pd.bdate_range("2025-11-03", periods=18).strftime("%Y-%m-%d").tolist()
    parts = []
    for day in days:
        part = reviewed_frame(day)
        part["symbol"] = "RELIANCE"
        part["research_eligible"] = True
        part["screen_status"] = "PASS_SCALE_SCREEN"
        parts.append(part)
    return (
        days,
        pd.concat(parts, ignore_index=True),
        {d: dict(slots=375, open_minute=555) for d in days},
    )


@pytest.mark.leakage
def test_history_holes_are_not_backfilled_and_current_day_never_enters_history():
    days, bars, calendar = history_fixture()
    setups, audit = causal_setups("RELIANCE", bars, calendar, include_noise=True)
    assert setups[days[15]].noise14 is not None
    assert audit[0]["prior_days"] == days[:15]
    changed = bars.copy()
    changed.loc[changed.session_date == days[15], "close"] = 100.5
    later, _ = causal_setups("RELIANCE", changed, calendar, include_noise=True)
    np.testing.assert_array_equal(setups[days[15]].noise14, later[days[15]].noise14)
    missing = bars.loc[bars.session_date != days[8]]
    broken, _ = causal_setups("RELIANCE", missing, calendar, include_noise=True)
    assert broken[days[-1]].noise14 is None
    assert broken[days[9]] is None


@pytest.mark.leakage
def test_signal_prefix_does_not_depend_on_future_exit_and_missing_history_is_unavailable():
    _, bars, _ = history_fixture()
    frame = bars.iloc[:375].reset_index(drop=True)
    frame.loc[29, "close"] = 101
    setup = Setup(100, noise14=np.full(375, 0.005))
    source = EquityInputs(
        "RELIANCE",
        frame,
        FeatureFrame("RELIANCE", frame.open_time, pd.DataFrame(), pd.DataFrame()),
        (),
        {},
    )
    day = frame.session_date.iloc[0]
    first = signal_frame("noise_vwap", source, {day: setup})
    changed = frame.copy()
    changed.loc[60:, "close"] = 100.05
    second = signal_frame("noise_vwap", replace(source, bars=changed), {day: setup})
    pd.testing.assert_frame_equal(first.values.iloc[:60], second.values.iloc[:60])
    unknown = signal_frame("noise_vwap", source, {day: None})
    assert not unknown.available.any().any() and unknown.values.isna().all().all()


def test_state_change_execution_rejects_nonbinary_targets():
    frame = reviewed_frame("2026-01-09")
    alpha = target(frame)
    alpha.values.iloc[29] = 0.5
    with pytest.raises(ValueError, match="binary"):
        run(frame, alpha)
    alpha = target(frame)
    alpha.values.iloc[100:110] = 1.0
    with pytest.raises(ValueError, match="at most one entry"):
        run(frame, alpha)


def test_paper_evaluator_records_real_shared_replay_and_rejects_input_drift(connection, tmp_path):
    from unittest.mock import MagicMock

    from sqlalchemy import Engine, text
    from test_equity_research import SNAPSHOT

    from helios.alpha.definition import AlphaDefinition, register_alpha_definition
    from helios.common.config import config_hash, load_config
    from helios.common.project_config import GatesConfig
    from helios.registry.api import RegistryError
    from helios.registry.experiments import register_experiment
    from helios.registry.gates import store_gate_config
    from helios.registry.results import Split, Status, get_result
    from helios.sim.equity_evaluation import EquityEvaluationContext, equity_gates_path
    from helios.sim.evaluate import evaluate

    selected_policy = policy(minimum_sessions=2)
    frames = [reviewed_frame(d) for d in ("2026-01-09", "2026-01-12", "2026-01-13")]
    bars = pd.concat(frames, ignore_index=True)
    values = pd.Series(0.0, index=bars.index, name="paper_fixture")
    for start in (375, 750):
        values.iloc[start + 29 : start + 89] = 1.0
    available = pd.Series(True, index=bars.index, name="paper_fixture")
    available.iloc[:375] = False
    features = FeatureFrame("EXAMPLE", bars.open_time, values.to_frame(), available.to_frame())
    source = EquityInputs(
        "EXAMPLE",
        bars,
        features,
        tuple(f.session_date.iloc[0] for f in frames),
        {"paper_signal_sha256": feature_digest(features)},
    )
    definition = AlphaDefinition(
        alpha_id="nse_t_paper_integrated",
        version=1,
        name="Synthetic integrated paper fixture",
        provenance="QUANT",
        feature_set_version="nse_paper_minute_features_v1",
        horizon_family="H-MINUTE",
        horizon_periods=1,
        expression="paper_fixture",
        author="test",
    )
    register_alpha_definition(connection, definition)
    connection.execute(text(SNAPSHOT), {"id": "c" * 64, "commit": "a" * 40})
    store_gate_config(
        connection, load_config(equity_gates_path(selected_policy), GatesConfig), author="test"
    )
    model = MagicMock()
    model.model_hash, model.calibration_hash = "e" * 64, "d" * 64
    parameters = dict(
        market="nse_cash",
        symbol="EXAMPLE",
        alpha_id=definition.alpha_id,
        policy_hash=config_hash(selected_policy),
        model_hash=model.model_hash,
        calibration_hash=model.calibration_hash,
        source_hashes={},
        execution_policy="paper_state_change_v1",
        input_hashes=source.hashes,
    )
    experiment = register_experiment(
        connection,
        hypothesis="Synthetic paper integration check",
        params=parameters,
        author="test",
        snapshot_id="c" * 64,
    )
    engine = MagicMock(spec=Engine)
    engine.begin.return_value.__enter__.return_value = connection
    context = EquityEvaluationContext(
        selected_policy, source, "c" * 64, model, {}, execution_policy="paper_state_change_v1"
    )
    result = evaluate(
        definition.alpha_id,
        Split.VALID,
        experiment.experiment_id,
        engine=engine,
        equity=context,
        output_dir=tmp_path,
        reported=False,
    )
    assert result.status is Status.REJECTED and not result.gate_results["G7"]
    assert result.periods == 2 and get_result(connection, result.run_id) == result
    import json

    artifact = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert len(artifact["fills"]) == 4
    assert artifact["coverage"]["complete"] == 2
    assert artifact["coverage"]["excluded"][0]["reason"] == "paper_history_unavailable"
    drift = replace(context, inputs=replace(source, hashes={"paper_signal_sha256": "0" * 64}))
    with pytest.raises(RegistryError, match="input hash"):
        evaluate(
            definition.alpha_id,
            Split.VALID,
            experiment.experiment_id,
            engine=engine,
            equity=drift,
            output_dir=tmp_path,
            reported=False,
        )
    with pytest.raises(RegistryError, match="preregistered"):
        evaluate(
            definition.alpha_id,
            Split.VALID,
            experiment.experiment_id,
            engine=engine,
            equity=replace(context, execution_policy="every_bar_v1"),
            output_dir=tmp_path,
            reported=False,
        )
