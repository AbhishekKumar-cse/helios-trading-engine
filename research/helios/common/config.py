"""YAML configuration loading (step 026).

Every HELIOS run is driven by YAML config files (gates, fees, universe, splits, ...).
`load_config` reads a YAML file and validates it against a pydantic model, so a wrong
value (for example text where a number is expected) stops the program with a clear
message instead of silently producing wrong results.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError


class ConfigError(Exception):
    """Raised when a config file is missing, is not valid YAML, or has invalid values."""


class HeliosConfig(BaseModel):
    """Base class for all HELIOS config models.

    - extra="forbid": unknown keys are errors, so typos like `sharpe_mn` are caught.
    - frozen=True: settings cannot be changed after loading (reproducible runs).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


def load_config[M: BaseModel](path: str | Path, model: type[M]) -> M:
    """Read the YAML file at `path` and return it validated as an instance of `model`."""
    file = Path(path)
    if not file.is_file():
        raise ConfigError(f"config file not found: {file}")

    try:
        with file.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle)  # safe_load never executes code from the file
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {file}: {exc}") from exc

    if not isinstance(data, dict):
        found = "an empty file" if data is None else type(data).__name__
        raise ConfigError(f"top level of {file} must be a mapping of key: value, found {found}")

    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"invalid values in {file}:\n{exc}") from exc
