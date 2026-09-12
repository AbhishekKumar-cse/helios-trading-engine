"""Tests for YAML config loading (step 026)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from helios.common.config import ConfigError, HeliosConfig, load_config

FIXTURES = Path(__file__).parent / "fixtures"


class SampleConfig(HeliosConfig):
    name: str
    sharpe_min: float
    fitness_min: float
    turnover_min: float
    turnover_max: float
    symbols: list[str]


def write(tmp_path: Path, text: str) -> Path:
    file = tmp_path / "config.yaml"
    file.write_text(text, encoding="utf-8")
    return file


def test_loads_sample_yaml() -> None:
    cfg = load_config(FIXTURES / "sample_config.yaml", SampleConfig)
    assert cfg.name == "sample"
    assert cfg.sharpe_min == 1.0
    assert cfg.turnover_max == 0.70
    assert cfg.symbols == ["BTCUSDT", "ETHUSDT"]


def test_accepts_str_path() -> None:
    cfg = load_config(str(FIXTURES / "sample_config.yaml"), SampleConfig)
    assert isinstance(cfg, SampleConfig)


def test_wrong_type_is_rejected(tmp_path: Path) -> None:
    text = (FIXTURES / "sample_config.yaml").read_text(encoding="utf-8")
    file = write(tmp_path, text.replace("sharpe_min: 1.0", "sharpe_min: one"))
    with pytest.raises(ConfigError, match="sharpe_min") as info:
        load_config(file, SampleConfig)
    assert isinstance(info.value.__cause__, ValidationError)


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    text = (FIXTURES / "sample_config.yaml").read_text(encoding="utf-8")
    file = write(tmp_path, text + "sharpe_mn: 2.0\n")  # typo
    with pytest.raises(ConfigError, match="sharpe_mn"):
        load_config(file, SampleConfig)


def test_missing_key_is_rejected(tmp_path: Path) -> None:
    file = write(tmp_path, "name: sample\nsharpe_min: 1.0\n")
    with pytest.raises(ConfigError, match="fitness_min"):
        load_config(file, SampleConfig)


def test_missing_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "does_not_exist.yaml", SampleConfig)


def test_invalid_yaml_is_rejected(tmp_path: Path) -> None:
    file = write(tmp_path, "name: [unclosed\n")
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_config(file, SampleConfig)


@pytest.mark.parametrize("text", ["", "- just\n- a list\n"])
def test_top_level_must_be_mapping(tmp_path: Path, text: str) -> None:
    file = write(tmp_path, text)
    with pytest.raises(ConfigError, match="must be a mapping"):
        load_config(file, SampleConfig)


def test_loaded_config_is_frozen() -> None:
    cfg = load_config(FIXTURES / "sample_config.yaml", SampleConfig)
    with pytest.raises(ValidationError):
        cfg.sharpe_min = 5.0  # type: ignore[misc]
