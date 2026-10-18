"""A single observed NSE session passed to the shared reference engine."""

from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import Field, model_validator

from helios.common.config import HeliosConfig, config_hash
from helios.common.market_clock import IST, nse_bar_complete, nse_reviewed_bar_complete
from helios.common.project_config import FeesConfig
from helios.common.types import Hash, Mode, Timestamp
from helios.equities.config import EquityResearchPolicy
from helios.registry.results import Split
from helios.sim.loss_risk import DailyRiskLimits
from helios.sim.strategy import ShareBarStrategyConfig


class EquityBacktestConfig(HeliosConfig):
    market: Literal["nse_cash"] = "nse_cash"
    run_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,40}$")
    alpha_id: str
    alpha_version: int = Field(default=1, ge=1)
    snapshot_id: Hash
    symbol: str = Field(pattern=r"^[A-Z0-9&-]+$")
    start_us: Timestamp
    end_us: Timestamp
    split: Literal[Split.VALID] = Split.VALID
    strategy: ShareBarStrategyConfig
    risk: DailyRiskLimits
    fees: FeesConfig
    policy: EquityResearchPolicy
    cost_multiplier: float = Field(default=1, ge=1, allow_inf_nan=False)
    mark_reference: Literal["bar_close_proxy"] = "bar_close_proxy"

    @model_validator(mode="after")
    def session_scope(self) -> Self:
        local = datetime.fromtimestamp(self.start_us / 1_000_000, UTC).astimezone(IST)
        short = (
            self.policy.version == "nse_minute_research_v2"
            and local.date().isoformat() == "2025-10-21"
        )
        opening = (13, 45) if short else (9, 15)
        if (local.hour, local.minute) != opening or not (
            self.policy.valid_start <= local.date() <= self.policy.valid_end
        ):
            raise ValueError("NSE replay must start at 09:15 inside the frozen VALID window")
        duration = 3_600_000_000 if self.policy.interval == "1h" else 60_000_000
        complete = (
            nse_reviewed_bar_complete
            if self.policy.version == "nse_minute_research_v2"
            else nse_bar_complete
        )
        if not complete(self.start_us, self.start_us + duration, self.policy.interval):
            raise ValueError("NSE backtest starts on an observed normal-session hour")
        if self.end_us - self.start_us != (60 if short else 375) * 60_000_000:
            raise ValueError("one complete 375-minute session is required")
        if self.strategy.mode is not Mode.BACKTEST or self.strategy.quantity_step != 1:
            raise ValueError("equity replay requires simulated whole-share orders")
        if self.strategy.strategy_id != self.run_id or self.risk.scope != self.run_id:
            raise ValueError("strategy and risk scopes must match")
        if len(self.risk.instruments) != 1 or self.risk.instruments[0].symbol != self.symbol:
            raise ValueError("one NSE instrument per scope")
        if config_hash(self.fees) != config_hash(
            self.policy.fees(self.symbol, self.cost_multiplier)
        ):
            raise ValueError("fees do not match the frozen equity cost policy")
        return self
