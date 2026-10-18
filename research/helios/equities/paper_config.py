"""NSE integration-only PAPER wiring, separate from candidate promotion."""

from decimal import Decimal
from typing import Literal, Self

from pydantic import Field, model_validator

from helios.common.config import HeliosConfig, config_hash
from helios.common.project_config import FeesConfig
from helios.common.types import Mode
from helios.equities.config import EquityResearchPolicy
from helios.sim.loss_risk import DailyRiskLimits
from helios.sim.portfolio_risk import PositionLimits
from helios.sim.strategy import ShareBarStrategyConfig


class EquityPaperConfig(HeliosConfig):
    version: Literal["nse_public_minute_paper_v1"] = "nse_public_minute_paper_v1"
    mode: Literal[Mode.PAPER] = Mode.PAPER
    is_simulated: Literal[True] = True
    purpose: Literal["integration_only_rejected_candidate"] = "integration_only_rejected_candidate"
    run_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,40}$")
    stream_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    alpha_id: str
    alpha_version: int = Field(default=1, ge=1)
    symbol: str = Field(pattern=r"^[A-Z0-9&-]+$")
    interval: Literal["1m"] = "1m"
    max_event_skew_us: int = Field(default=5_000_000, ge=0, le=5_000_000)
    max_intent_age_us: int = Field(default=10_000_000, gt=0, le=10_000_000)
    strategy: ShareBarStrategyConfig
    risk: DailyRiskLimits
    fees: FeesConfig
    research_policy: EquityResearchPolicy
    fill_model: Literal["later_received_public_price_proxy_v1"] = (
        "later_received_public_price_proxy_v1"
    )

    @model_validator(mode="after")
    def one_simulated_inr_instrument(self) -> Self:
        if (
            self.strategy.mode is not Mode.PAPER
            or self.strategy.quantity_step != 1
            or self.strategy.strategy_id != self.run_id
            or self.risk.scope != self.run_id
            or len(self.risk.instruments) != 1
            or self.risk.instruments[0].symbol != self.symbol
            or self.research_policy.interval != "1m"
            or config_hash(self.fees) != config_hash(self.research_policy.fees(self.symbol))
        ):
            raise ValueError("NSE PAPER requires one whole-share INR scope and frozen cost policy")
        return self


def equity_paper_config(
    run_id: str, stream_id: str, alpha_id: str, symbol: str
) -> EquityPaperConfig:
    policy = EquityResearchPolicy(version="nse_minute_research_v1", interval="1m")
    return EquityPaperConfig(
        run_id=run_id,
        stream_id=stream_id,
        alpha_id=alpha_id,
        symbol=symbol,
        research_policy=policy,
        fees=policy.fees(symbol),
        strategy=ShareBarStrategyConfig(
            strategy_id=run_id,
            capital=policy.capital,
            max_weight=Decimal(".1"),
            rebalance_threshold=Decimal(".001"),
            quantity_step=Decimal(1),
            mode=Mode.PAPER,
        ),
        risk=DailyRiskLimits(
            scope=run_id,
            daily_loss_limit=Decimal(1000),
            max_gross_exposure=Decimal(20000),
            instruments=(
                PositionLimits(
                    symbol=symbol,
                    max_order_notional=Decimal(20000),
                    max_position_notional=Decimal(20000),
                    price_band_fraction=Decimal(".2"),
                    median_window=1,
                    max_price_age_us=5_000_000,
                ),
            ),
        ),
    )
