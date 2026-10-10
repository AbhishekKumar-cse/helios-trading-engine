"""Fixed formulas, the common bounded pipeline and insert-only DRAFT registration."""

import runpy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import Connection, text

from helios.alpha.definition import load_alpha_definition, register_alpha_definition
from helios.alpha.output import evaluate_definition
from helios.features.runner import FeatureFrame
from helios.registry.api import RegistryError, get_alpha
from helios.registry.lifecycle import INITIAL, AlphaState

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / "configs/alphas/baselines"
FILES = ("b0_momentum.yaml", "b1_reversal.yaml", "b2_taker_flow.yaml")
EXPRESSIONS = ("sign(log_return_24)", "-zscore(log_return_1, 168)", "zscore(taker_buy_ratio, 168)")
main = runpy.run_path(str(ROOT / "scripts/register_baselines.py"))["main"]


@pytest.mark.parametrize("number", [0, 1, 2])
def test_fixed_definition_and_golden_bounded_output(number: int) -> None:
    definition = load_alpha_definition(DIRECTORY / FILES[number])
    assert definition.alpha_id == f"baseline_b{number}"
    assert definition.expression == EXPRESSIONS[number]
    assert definition.horizon_family.value == "H-HOURLY" and definition.horizon_periods == 1
    assert definition.free_parameter_count == (0 if number == 0 else 1)
    x = np.arange(1.0, 169.0)
    values = pd.DataFrame(
        {
            "log_return_24": np.resize([-0.2, 0.0, 0.1], 168),
            "log_return_1": x / 1000,
            "taker_buy_ratio": x / 169,
        }
    )
    frame = FeatureFrame(
        "BTCUSDT",
        pd.Series(np.arange(168) * 3_600_000_000),
        values,
        pd.DataFrame(True, index=values.index, columns=values.columns),
    )
    result = evaluate_definition(definition, frame, interval="1h")
    if number == 0:
        np.testing.assert_array_equal(result.values, np.resize([-1.0, 0.0, 1.0], 168))
        assert result.available.all()
    else:
        assert not result.available.iloc[:167].any()
        assert result.values.iloc[:167].isna().all()
        assert result.values.iloc[167] == (-1 if number == 1 else 1)


def test_check_only_avoids_database(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden() -> None:
        pytest.fail("check-only must not contact PostgreSQL")

    monkeypatch.setitem(main.__globals__, "get_engine", forbidden)
    assert main(["--check-only"]) == 0


def test_invalid_batch_avoids_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden() -> None:
        pytest.fail("invalid batch must not contact PostgreSQL")

    monkeypatch.setitem(main.__globals__, "get_engine", forbidden)
    assert main(["--directory", str(tmp_path)]) == 2


def test_baselines_round_trip_without_results(connection: Connection) -> None:
    for number, filename in enumerate(FILES):
        definition = load_alpha_definition(DIRECTORY / filename).model_copy(
            update={"alpha_id": f"t_baseline_b{number}"}
        )
        register_alpha_definition(connection, definition)
        assert get_alpha(connection, definition.alpha_id, 1).spec == definition.to_registry().spec
        assert (
            connection.execute(
                text("SELECT count(*) FROM alpha_results WHERE alpha_id=:id"),
                {"id": definition.alpha_id},
            ).scalar_one()
            == 0
        )
    assert INITIAL is AlphaState.DRAFT


def test_duplicate_rolls_back_batch(connection: Connection) -> None:
    definitions = [
        load_alpha_definition(DIRECTORY / name).model_copy(
            update={"alpha_id": f"t_batch_baseline_b{n}"}
        )
        for n, name in enumerate(FILES)
    ]
    register_alpha_definition(connection, definitions[1])
    with pytest.raises(RegistryError):
        with connection.begin_nested():
            for definition in definitions:
                register_alpha_definition(connection, definition)
    assert (
        connection.execute(
            text("SELECT count(*) FROM alpha_definitions WHERE alpha_id=:id"),
            {"id": definitions[0].alpha_id},
        ).scalar_one()
        == 0
    )
