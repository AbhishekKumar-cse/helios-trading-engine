"""YAML configuration loading (step 026) and config fingerprints (step 027).

Every HELIOS run is driven by YAML config files (gates, fees, universe, splits, ...).
`load_config` reads a YAML file and validates it against a pydantic model, so a wrong
value (for example text where a number is expected) stops the program with a clear
message instead of silently producing wrong results.

`config_hash` gives every loaded config a SHA-256 fingerprint. It is stored with every
result, so we can always tell exactly which settings produced it (reproducibility rule).
"""

from __future__ import annotations

import hashlib
import json
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


def canonical_json(config: BaseModel) -> str:
    """Stable text form of a config: keys sorted at every level, no spaces, UTF-8.

    The same values always give the same text, whatever order the keys had in the
    YAML file or however numbers were written (0.70 and 0.7 are the same value).
    """
    data = config.model_dump(mode="json")
    return json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,  # NaN/inf are not valid JSON and never belong in a config
    )


def config_hash(config: BaseModel) -> str:
    """SHA-256 fingerprint (64 hex characters) of the config's canonical JSON."""
    return hashlib.sha256(canonical_json(config).encode("utf-8")).hexdigest()
