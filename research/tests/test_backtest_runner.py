import csv
from contextlib import contextmanager, nullcontext
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError
from test_loss_risk import Store

from helios.backtest.config import BacktestConfig
from helios.backtest.engine import simulate
from helios.backtest.inputs import load_inputs
from helios.backtest.runner import BacktestArtifact, preregister, run_backtest
from helios.common.config import load_config
from helios.common.lineage import RunContext
from helios.data.binance import sha256_file
from helios.data.snapshots import SnapshotFile, compute_snapshot_id
from helios.registry.api import AlphaDefinition
from helios.registry.experiments import ExperimentStatus, get_experiment

CONFIG = Path("configs/backtests/hand_scenario.yaml")


def config(scope="test_backtest", **changes):
    raw = load_config(CONFIG, BacktestConfig).model_dump()
    raw["strategy"]["strategy_id"] = raw["risk"]["scope"] = raw["run_id"] = scope
    return BacktestConfig.model_validate(raw | changes)


def definition(selected):
    return AlphaDefinition(
        alpha_id=selected.alpha_id,
        version=selected.alpha_version,
        name="Synthetic fixture",
        feature_set_version="synthetic_hand_v1",
        horizon_family="H-HOURLY",
        horizon_periods=1,
        author="test",
        spec={"synthetic_csv_sha256": selected.csv_sha256, "is_synthetic": True},
    )


def inputs(selected):
    return load_inputs(
        selected,
        definition(selected),
        RunContext.capture(selected, selected.snapshot_id, 0, reported=False),
    )


@pytest.fixture
def engine(connection):
    # Every app transaction is a savepoint inside the rolled-back test fixture.
    @contextmanager
    def transaction():
        with connection.begin_nested():
            yield connection

    engine = MagicMock(spec=Engine)
    engine.begin.side_effect = transaction
    engine.connect.side_effect = lambda: nullcontext(connection)
    connection.execute(
        text("""INSERT INTO instruments
        (symbol,base_asset,quote_asset,tick_size,lot_size,first_available_date)
        VALUES ('BTCUSDT','BTC','USDT',.01,.00001,'2020-01-01') ON CONFLICT(symbol) DO NOTHING""")
    )
    return engine


@pytest.mark.parametrize(
    "changes",
    [
        {"split": "test"},
        {"mode": "PAPER"},
        {"start_us": 0},
        {"csv_sha256": None},
        {"end_us": 1609459200000001},
    ],
)
def test_invalid_config_refused_before_any_data_read(changes):
    with pytest.raises(ValidationError):
        config(**changes)


def test_shared_runner_matches_fixed_sheet_and_is_deterministic():
    selected = config()
    batch = inputs(selected)
    one = simulate(selected, batch.bars, batch.signals, Store())
    assert one == simulate(selected, batch.bars, batch.signals, Store())
    with Path(selected.csv_path).open() as handle:
        rows = list(csv.DictReader(handle))
    for row, snapshot, position in zip(rows, one.snapshots, one.positions, strict=True):
        for field, key in (
            ("cash", "cash"),
            ("equity", "equity"),
            ("realized_pnl", "realized_pnl"),
            ("unrealized_pnl", "unrealized_pnl"),
            ("fees", "fees_total"),
        ):
            assert getattr(snapshot, field) == D(row[key])
        assert position.quantity == D(row["position_quantity"])
        assert (position.average_entry_price or 0) == D(row["average_cost"])
    assert [r.fill.price for r in one.reports if r.fill] == [
        D("100.02"),
        D("120.024"),
        D("109.978"),
    ]
    assert not one.tail


def test_loss_trip_blocks_new_exposure_and_input_gaps_refuse():
    raw = config().model_dump()
    raw["risk"]["daily_loss_limit"] = D(1)
    selected = BacktestConfig.model_validate(raw)
    batch = inputs(selected)
    store = Store()
    trace = simulate(selected, batch.bars, batch.signals, store)
    assert len(trace.orders) == 2 and trace.positions[-1].quantity == 2
    assert len(store.events) == 1 and store.events[0].reason.value == "DAILY_LOSS_LIMIT"
    with pytest.raises(ValueError, match="contiguous"):
        simulate(
            selected,
            batch.bars[:3] + batch.bars[4:],
            batch.signals[:3] + batch.signals[4:],
            Store(),
        )


@pytest.mark.parametrize("dirty", [False, True])
def test_run_persists_owned_orders_fills_snapshots_and_immutable_lineage(
    engine, connection, tmp_path, monkeypatch, dirty
):
    monkeypatch.setattr("helios.common.lineage.git_is_dirty", lambda *_: dirty)
    selected = preregister(config(), engine=engine, reported=False)
    path = run_backtest(selected, engine=engine, output_dir=tmp_path, reported=False)
    artifact = BacktestArtifact.model_validate_json(path.read_text())
    assert artifact.config == selected and artifact.trace.snapshots[-1].equity == D("1019.340022")
    row = connection.execute(
        text("SELECT * FROM backtest_runs WHERE bt_run_id=:id"), {"id": selected.run_id}
    ).one()
    assert row.mode == "BACKTEST" and row.status == "finished"
    assert row.dirty is artifact.context.dirty is dirty
    assert row.code_commit == artifact.context.code_commit
    assert row.artifact_sha256 == sha256_file(path)
    for table, count in (("orders", 3), ("positions_snapshot", 10), ("pnl_snapshots", 10)):
        assert (
            connection.execute(
                text(f"SELECT count(*) FROM {table} WHERE bt_run_id=:id"), {"id": selected.run_id}
            ).scalar_one()
            == count
        )
    assert (
        connection.execute(
            text("""SELECT count(*) FROM fills f JOIN orders o USING(order_id)
        WHERE o.bt_run_id=:id AND o.is_simulated"""),
            {"id": selected.run_id},
        ).scalar_one()
        == 3
    )
    assert get_experiment(connection, selected.experiment_id).status is ExperimentStatus.FINISHED
    with patch("helios.backtest.runner.load_inputs") as loader:
        with pytest.raises(ValueError, match="consumed"):
            run_backtest(selected, engine=engine, output_dir=tmp_path, reported=False)
        loader.assert_not_called()
    with pytest.raises(DBAPIError, match="immutable"), connection.begin_nested():
        connection.execute(
            text("UPDATE backtest_runs SET seed=1 WHERE bt_run_id=:id"), {"id": selected.run_id}
        )


def test_tampered_input_retains_failed_attempt_without_partial_trades(engine, connection, tmp_path):
    original = config()
    path = tmp_path / "fixture.csv"
    path.write_bytes(Path(original.csv_path).read_bytes())
    file = SnapshotFile(str(path), sha256_file(path), path.stat().st_size)
    selected = preregister(
        config(csv_path=str(path), snapshot_id=compute_snapshot_id([file])),
        engine=engine,
        reported=False,
    )
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ValueError, match="checksum"):
        run_backtest(selected, engine=engine, output_dir=tmp_path, reported=False)
    assert (
        connection.execute(
            text("SELECT status FROM backtest_runs WHERE bt_run_id=:id"), {"id": selected.run_id}
        ).scalar_one()
        == "failed"
    )

    assert (
        connection.execute(
            text("SELECT count(*) FROM orders WHERE bt_run_id=:id"), {"id": selected.run_id}
        ).scalar_one()
        == 0
    )
    assert get_experiment(connection, selected.experiment_id).status is ExperimentStatus.ABANDONED


def test_changed_protocol_refuses_before_loading_and_duplicate_preregistration(engine):
    selected = preregister(config(), engine=engine, reported=False)
    with pytest.raises(ValueError, match="preregistered"):
        preregister(config(), engine=engine, reported=False)
    raw = selected.model_dump()
    raw["strategy"]["rebalance_threshold"] = D(".01")
    with patch("helios.backtest.runner.load_inputs") as loader:
        with pytest.raises(ValueError, match="exact backtest"):
            run_backtest(BacktestConfig.model_validate(raw), engine=engine, reported=False)
        loader.assert_not_called()


def test_registered_expression_adapter_preserves_missing_alpha_and_verifies_features(tmp_path):
    from types import SimpleNamespace

    import pandas as pd

    from helios.features.runner import FeatureFrame

    base = config()
    batch = inputs(base)
    selected = config(data_kind="registered_hourly", csv_path=None, csv_sha256=None)
    stored = definition(selected).model_copy(
        update=dict(spec={"expression": "log_return_1", "params": {}}, feature_set_version="v1")
    )
    root = tmp_path / "feature_set=v1/interval=1h/symbol=BTCUSDT"
    root.mkdir(parents=True)
    file = root / "features.parquet"
    file.write_bytes(b"synthetic feature fixture")
    import json

    (root / "manifest.json").write_text(
        json.dumps(
            dict(
                input_snapshot=dict(files=[dict(path="bars.parquet", sha256="a" * 64)]),
                files=[dict(path=file.name, sha256=sha256_file(file))],
            )
        )
    )
    frame = FeatureFrame(
        "BTCUSDT",
        pd.Series([b.open_time for b in batch.bars]),
        pd.DataFrame({"log_return_1": [float("nan")] + [0.1] * 9}),
        pd.DataFrame({"log_return_1": [False] + [True] * 9}),
    )
    with (
        patch("helios.backtest.inputs.HistoricalBarSource") as source,
        patch("helios.backtest.inputs.DEFAULT_FEATURE_DIR", tmp_path),
        patch(
            "helios.backtest.inputs.load_manifest",
            return_value=SimpleNamespace(files=[SnapshotFile("bars.parquet", "a" * 64, 1)]),
        ),
        patch("helios.backtest.inputs.load_feature_frame", return_value=frame),
    ):
        source.return_value.events.side_effect = lambda: iter(batch.bars)
        context = RunContext.capture(selected, selected.snapshot_id, 0, reported=False)
        loaded = load_inputs(selected, stored, context)
        assert loaded.signals[0].value is None
        assert all(signal.value == 0.1 for signal in loaded.signals[1:])
        file.write_bytes(b"tampered")
        with pytest.raises(ValueError, match="checksum"):
            load_inputs(selected, stored, context)


def test_results_transaction_rolls_back_if_finalize_fails(engine, connection, tmp_path):
    from helios.backtest.runner import _persist

    selected = preregister(config(), engine=engine, reported=False)

    def fail(*args):
        _persist(*args)
        raise ValueError("injected finalize failure")

    with patch("helios.backtest.runner._persist", side_effect=fail):
        with pytest.raises(ValueError, match="injected"):
            run_backtest(selected, engine=engine, output_dir=tmp_path, reported=False)
    for table in ("orders", "pnl_snapshots", "positions_snapshot"):
        assert (
            connection.execute(
                text(f"SELECT count(*) FROM {table} WHERE bt_run_id=:id"), {"id": selected.run_id}
            ).scalar_one()
            == 0
        )
    assert (
        connection.execute(
            text("SELECT status FROM backtest_runs WHERE bt_run_id=:id"), {"id": selected.run_id}
        ).scalar_one()
        == "failed"
    )
