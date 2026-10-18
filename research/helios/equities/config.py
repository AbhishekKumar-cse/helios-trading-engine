"""Frozen development protocol; costs are explicit proxies, not broker billing."""

from datetime import date
from decimal import Decimal
from typing import Literal, Self

from pydantic import Field, StrictInt, model_validator

from helios.common.config import HeliosConfig
from helios.common.project_config import FeesConfig


class EquityResearchPolicy(HeliosConfig):
    version: Literal[
        "nse_hourly_research_v1", "nse_minute_research_v1", "nse_minute_research_v2"
    ] = "nse_hourly_research_v1"
    market: Literal["nse_cash"] = "nse_cash"
    interval: Literal["1h", "1m"] = "1h"
    quote_asset: Literal["INR"] = "INR"
    session: Literal["observed_complete_normal_session_v1", "reviewed_sessions_v2"] = (
        "observed_complete_normal_session_v1"
    )
    train_end: date = date(2025, 12, 31)
    valid_start: date = date(2026, 1, 9)
    valid_end: date = date(2026, 6, 30)
    capital: Decimal = Field(default=Decimal("100000"), gt=0)
    max_weight: Decimal = Field(default=Decimal("0.5"), gt=0, le=1)
    commission_tax_proxy_bps: float = Field(default=15, ge=0, lt=1000, allow_inf_nan=False)
    slippage_proxy_bps: float = Field(default=5, ge=0, lt=1000, allow_inf_nan=False)
    trading_sessions_per_year: StrictInt = Field(default=252, ge=1)
    minimum_sessions: StrictInt = Field(default=30, ge=2)
    minimum_coverage: float = Field(default=0.9, gt=0, le=1)
    seed: StrictInt = Field(default=42, ge=0)

    @model_validator(mode="after")
    def frozen_frequency(self) -> Self:
        if self.version == "nse_minute_research_v2":
            if (
                self.interval != "1m"
                or self.session != "reviewed_sessions_v2"
                or self.charge_policy != "intraday_reference_v2"
                or self.commission_tax_proxy_bps != 0
            ):
                raise ValueError("v2 requires reviewed minute sessions and explicit reference fees")
        elif self.session != "observed_complete_normal_session_v1":
            raise ValueError("v1 assumptions must remain unchanged")
        expected = "nse_hourly_research_v1" if self.interval == "1h" else "nse_minute_research_v1"
        if (
            self.version != expected and self.version != "nse_minute_research_v2"
        ) or not self.train_end < self.valid_start < self.valid_end:
            raise ValueError("equity version/frequency and chronological split must agree")
        return self

    @property
    def feature_set_version(self) -> str:
        return (
            "nse_reviewed_minute_features_v2"
            if self.version == "nse_minute_research_v2"
            else "nse_session_features_v1"
        )

    @property
    def charge_policy(self) -> str:
        return (
            "intraday_reference_v2" if self.version == "nse_minute_research_v2" else "flat_proxy_v1"
        )

    @property
    def full_slots(self) -> int:
        return 6 if self.interval == "1h" else 375

    @property
    def session_slots(self) -> int:
        return 7 if self.interval == "1h" else 375

    def fees(self, symbol: str, multiplier: float = 1) -> FeesConfig:
        return FeesConfig(
            version=(
                "nse_intraday_reference_v2"
                if self.charge_policy == "intraday_reference_v2"
                else "nse_research_cost_proxy_v1"
            ),
            exchange="nse_cash",
            source_url="https://zerodha.com/charges/",
            checked_on=date(2026, 10, 17),
            tier=(
                "ASSUMPTION: current public brokerage scenario plus dated statutory estimate"
                if self.version == "nse_minute_research_v2"
                else "ASSUMPTION: flat commission/tax proxy; not a verified broker tariff"
            ),
            maker_fee_bps=self.commission_tax_proxy_bps * multiplier,
            taker_fee_bps=self.commission_tax_proxy_bps * multiplier,
            slippage_bps={symbol: self.slippage_proxy_bps * multiplier},
        )
