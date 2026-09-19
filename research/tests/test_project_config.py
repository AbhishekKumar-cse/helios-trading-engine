"""The real config files in configs/ load and match the accepted ADRs (step 036)."""

from datetime import date
from pathlib import Path

import pytest

from helios.common.config import ConfigError, config_hash
from helios.common.project_config import (
    CONFIG_DIR,
    HorizonFamily,
    load_fees,
    load_gates,
    load_splits,
    load_universe,
)


def test_gates_match_adr_002() -> None:
    g = load_gates()
    assert (g.sharpe_min, g.fitness_min, g.fitness_turnover_floor) == (1.0, 1.0, 0.125)
    assert (g.turnover_min, g.turnover_max) == (0.01, 0.70)
    assert g.require_out_of_sample is True
    assert (g.stability_subperiod, g.stability_min_positive_fraction) == ("month", 0.5)
    assert (g.cost_stress_multiplier, g.cost_stress_sharpe_min) == (2.0, 0.0)


def test_universe_has_five_usdt_coins() -> None:
    u = load_universe()
    assert u.symbols == ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]


def test_fees_match_adr_005_and_cover_universe() -> None:
    f = load_fees()
    assert f.checked_on == date(2026, 9, 20)
    assert (f.maker_fee_bps, f.taker_fee_bps) == (10.0, 10.0)
    assert set(f.slippage_bps) == set(load_universe().symbols)
    assert f.cost_bps("BTCUSDT") == 12.0
    assert f.cost_bps("XRPUSDT") == 15.0
    with pytest.raises(KeyError):
        f.cost_bps("DOGEUSDT")


def test_splits_match_adr_003_and_004() -> None:
    s = load_splits()
    hourly = s.families[HorizonFamily.HOURLY]
    minute = s.families[HorizonFamily.MINUTE]
    assert (hourly.periods_per_year, hourly.embargo_days) == (8760, 7)
    assert (minute.periods_per_year, minute.embargo_days) == (525600, 1)
    assert (hourly.train.days, hourly.valid.days, hourly.test.days) == (1826, 540, 785)
    assert (minute.train.days, minute.valid.days, minute.test.days) == (365, 180, 183)
    assert hourly.test.end == minute.test.end == date(2026, 8, 31)


def test_every_config_has_a_stable_hash() -> None:
    assert config_hash(load_gates()) == config_hash(load_gates())
    assert config_hash(load_universe()) == config_hash(load_universe())
    assert config_hash(load_fees()) == config_hash(load_fees())
    assert config_hash(load_splits()) == config_hash(load_splits())


# ---------------------------------------------------------------- bad values are rejected


def edited(tmp_path: Path, name: str, old: str, new: str) -> Path:
    text = (CONFIG_DIR / name).read_text(encoding="utf-8")
    assert old in text
    out = tmp_path / name
    out.write_text(text.replace(old, new), encoding="utf-8")
    return out


def test_turnover_min_above_max_is_rejected(tmp_path: Path) -> None:
    bad = edited(tmp_path, "gates_v1.yaml", "turnover_min: 0.01", "turnover_min: 0.90")
    with pytest.raises(ConfigError, match="turnover_min must be smaller"):
        load_gates(bad)


def test_wrong_embargo_gap_is_rejected(tmp_path: Path) -> None:
    bad = edited(tmp_path, "splits.yaml", "start: 2023-01-08", "start: 2023-01-02")
    with pytest.raises(ConfigError, match="embargo"):
        load_splits(bad)


def test_bad_symbol_is_rejected(tmp_path: Path) -> None:
    bad = edited(tmp_path, "universe.yaml", "- XRPUSDT", "- xrpbtc")
    with pytest.raises(ConfigError, match="quoted in USDT"):
        load_universe(bad)


def test_unknown_horizon_family_is_rejected(tmp_path: Path) -> None:
    bad = edited(tmp_path, "splits.yaml", "H-MINUTE:", "H-DAILY:")
    with pytest.raises(ConfigError, match="families"):
        load_splits(bad)


def test_negative_slippage_is_rejected(tmp_path: Path) -> None:
    bad = edited(tmp_path, "fees.yaml", "BTCUSDT: 2.0", "BTCUSDT: -2.0")
    with pytest.raises(ConfigError, match="slippage must be >= 0"):
        load_fees(bad)
