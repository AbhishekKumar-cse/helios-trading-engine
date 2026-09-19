"""Typed models for the project config files in `configs/` (step 036).

Each YAML file has one pydantic model here. `load_config` (step 026) reads the file and the
model rejects typos, wrong types and impossible values (for example turnover_min above
turnover_max). The decisions behind the values are in docs/decisions/ADR-002 to ADR-005.
"""

from __future__ import annotations

from datetime import date, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from helios.common.config import HeliosConfig, load_config

# research/helios/common/project_config.py -> parents[3] is the project root
CONFIG_DIR = Path(__file__).resolve().parents[3] / "configs"


class HorizonFamily(StrEnum):
    """Horizon families from ADR-003."""

    HOURLY = "H-HOURLY"
    MINUTE = "H-MINUTE"
    SECOND = "H-SECOND"
    MICRO = "H-MICRO"


# ---------------------------------------------------------------- gates (ADR-002)


class GatesConfig(HeliosConfig):
    """Alpha selection gates G1 to G6 (`configs/gates_v1.yaml`)."""

    version: str
    sharpe_min: float  # G1
    fitness_min: float  # G2
    fitness_turnover_floor: float = Field(gt=0)
    turnover_min: float = Field(gt=0, lt=1)  # G3
    turnover_max: float = Field(gt=0, le=1)
    require_out_of_sample: bool  # G4
    stability_subperiod: Literal["week", "month"]  # G5
    stability_min_positive_fraction: float = Field(ge=0, le=1)
    cost_stress_multiplier: float = Field(ge=1)  # G6
    cost_stress_sharpe_min: float

    @model_validator(mode="after")
    def _turnover_range(self) -> Self:
        if self.turnover_min >= self.turnover_max:
            raise ValueError("turnover_min must be smaller than turnover_max")
        return self


# ---------------------------------------------------------------- universe


class UniverseConfig(HeliosConfig):
    """Coins HELIOS trades (`configs/universe.yaml`)."""

    version: str
    exchange: str
    quote: str
    symbols: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _symbols_valid(self) -> Self:
        if len(set(self.symbols)) != len(self.symbols):
            raise ValueError("symbols must be unique")
        for s in self.symbols:
            if s != s.upper() or not s.endswith(self.quote) or s == self.quote:
                raise ValueError(f"symbol {s!r} must be upper-case and quoted in {self.quote}")
        return self


# ---------------------------------------------------------------- fees (ADR-005)


class FeesConfig(HeliosConfig):
    """Trading fees and slippage (`configs/fees.yaml`)."""

    version: str
    exchange: str
    source_url: str
    checked_on: date
    tier: str
    maker_fee_bps: float = Field(ge=0)
    taker_fee_bps: float = Field(ge=0)
    slippage_bps: dict[str, float]

    @model_validator(mode="after")
    def _slippage_non_negative(self) -> Self:
        bad = [s for s, v in self.slippage_bps.items() if v < 0]
        if bad:
            raise ValueError(f"slippage must be >= 0 for {bad}")
        return self

    def cost_bps(self, symbol: str) -> float:
        """One-side simulator cost for `symbol`: taker fee + slippage (ADR-005 section 3)."""
        if symbol not in self.slippage_bps:
            raise KeyError(f"no slippage configured for {symbol}")
        return self.taker_fee_bps + self.slippage_bps[symbol]


# ---------------------------------------------------------------- splits (ADR-003, ADR-004)


class DateRange(HeliosConfig):
    """Inclusive range of UTC calendar days."""

    start: date
    end: date

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.start > self.end:
            raise ValueError(f"start {self.start} is after end {self.end}")
        return self

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


class FamilySplits(HeliosConfig):
    """TRAIN / VALID / TEST ranges of one horizon family, separated by the embargo."""

    periods_per_year: int = Field(gt=0)
    embargo_days: int = Field(ge=0)
    train: DateRange
    valid: DateRange
    test: DateRange

    @model_validator(mode="after")
    def _chronological_with_embargo(self) -> Self:
        for earlier, later, name in (
            (self.train, self.valid, "train -> valid"),
            (self.valid, self.test, "valid -> test"),
        ):
            gap = (later.start - earlier.end - timedelta(days=1)).days
            if gap != self.embargo_days:
                raise ValueError(f"{name}: gap is {gap} days, embargo_days is {self.embargo_days}")
        return self


class SplitsConfig(HeliosConfig):
    """Splits per horizon family (`configs/splits.yaml`)."""

    version: str
    families: dict[HorizonFamily, FamilySplits] = Field(min_length=1)


# ---------------------------------------------------------------- loaders


def load_gates(path: Path = CONFIG_DIR / "gates_v1.yaml") -> GatesConfig:
    return load_config(path, GatesConfig)


def load_universe(path: Path = CONFIG_DIR / "universe.yaml") -> UniverseConfig:
    return load_config(path, UniverseConfig)


def load_fees(path: Path = CONFIG_DIR / "fees.yaml") -> FeesConfig:
    return load_config(path, FeesConfig)


def load_splits(path: Path = CONFIG_DIR / "splits.yaml") -> SplitsConfig:
    return load_config(path, SplitsConfig)
