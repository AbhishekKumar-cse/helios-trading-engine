from decimal import Decimal
from typing import Literal, Self

from pydantic import Field, model_validator

from helios.common.config import HeliosConfig, config_hash
from helios.common.project_config import FeesConfig, load_fees
from helios.common.types import Mode
from helios.sim.loss_risk import DailyRiskLimits
from helios.sim.portfolio_risk import PositionLimits
from helios.sim.strategy import BarStrategyConfig


class PaperConfig(HeliosConfig):
    version: Literal["public_minute_paper_v1"] = "public_minute_paper_v1"
    mode: Literal[Mode.PAPER] = Mode.PAPER
    is_simulated: Literal[True] = True
    purpose: Literal["integration_only_rejected_candidate"] = "integration_only_rejected_candidate"
    run_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,40}$")
    stream_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    alpha_id: str = "minute_h04"
    alpha_version: int = Field(default=1, ge=1)
    symbol: Literal["BTCUSDT"] = "BTCUSDT"
    interval: Literal["1m"] = "1m"
    seconds: float = Field(default=240, gt=0, le=86_400, allow_inf_nan=False)
    endpoint: Literal["data", "spot443", "spot9443"] = "spot443"
    max_event_skew_us: int = Field(default=5_000_000, ge=0, le=5_000_000)
    max_intent_age_us: int = Field(default=10_000_000, gt=0, le=10_000_000)
    strategy: BarStrategyConfig
    risk: DailyRiskLimits
    fees: FeesConfig = Field(default_factory=load_fees)
    fill_model: Literal["later_received_public_price_proxy_v1"] = (
        "later_received_public_price_proxy_v1"
    )

    @model_validator(mode="after")
    def _scope(self) -> Self:
        if (
            self.strategy.mode is not Mode.PAPER
            or self.strategy.strategy_id != self.run_id
            or self.risk.scope != self.run_id
            or len(self.risk.instruments) != 1
            or self.risk.instruments[0].symbol != self.symbol
            or config_hash(self.fees) != config_hash(load_fees())
        ):
            raise ValueError("PAPER requires one matching scope/instrument and accepted costs")
        return self


def smoke_config(
    run_id: str, stream_id: str, *, seconds: float = 240, endpoint: str = "spot443"
) -> PaperConfig:
    return PaperConfig(
        run_id=run_id,
        stream_id=stream_id,
        seconds=seconds,
        endpoint=endpoint,
        strategy=BarStrategyConfig(
            capital=Decimal("1000"),
            max_weight=Decimal("0.01"),
            rebalance_threshold=Decimal("0.001"),
            strategy_id=run_id,
            mode=Mode.PAPER,
        ),
        risk=DailyRiskLimits(
            scope=run_id,
            daily_loss_limit=Decimal("5"),
            max_gross_exposure=Decimal("20"),
            instruments=(
                PositionLimits(
                    symbol="BTCUSDT",
                    max_order_notional=Decimal("30"),
                    max_position_notional=Decimal("20"),
                    price_band_fraction=Decimal("0.05"),
                    median_window=1,
                    max_price_age_us=5_000_000,
                ),
            ),
        ),
    )
