from typing import Literal, Self

from pydantic import Field, StrictInt, model_validator

from helios.common.config import HeliosConfig, config_hash
from helios.common.project_config import FeesConfig, load_fees
from helios.common.types import Hash, Mode, Timestamp
from helios.registry.results import Split
from helios.sim.loss_risk import DailyRiskLimits
from helios.sim.splits import split_window
from helios.sim.strategy import BarStrategyConfig


class BacktestConfig(HeliosConfig):
    version: Literal["bar_backtest_v1"] = "bar_backtest_v1"
    mode: Literal[Mode.BACKTEST] = Mode.BACKTEST
    run_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,40}$")
    experiment_id: StrictInt | None = Field(default=None, ge=1)
    alpha_id: str
    alpha_version: StrictInt = Field(default=1, ge=1)
    snapshot_id: Hash
    seed: StrictInt = Field(default=0, ge=0, le=2**32 - 1)
    symbol: str = Field(pattern=r"^[A-Z0-9]+USDT$")
    interval: Literal["1h"] = "1h"
    split: Split
    data_kind: Literal["synthetic_csv", "registered_hourly"]
    csv_path: str | None = None
    csv_sha256: Hash | None = None
    start_us: Timestamp
    end_us: Timestamp
    strategy: BarStrategyConfig
    risk: DailyRiskLimits
    fees: FeesConfig = Field(default_factory=load_fees)
    mark_reference: Literal["bar_close_proxy"] = "bar_close_proxy"

    @model_validator(mode="after")
    def _boundaries(self) -> Self:
        if self.split is Split.TEST:
            raise ValueError("this bar runner accepts TRAIN/VALID only; TEST is not authorized")
        window = split_window(self.split, interval=self.interval)
        if not window.start_us <= self.start_us < self.end_us <= window.end_us:
            raise ValueError("backtest bounds must remain inside the declared split")
        if self.start_us % 3_600_000_000 or self.end_us % 3_600_000_000:
            raise ValueError("backtest bounds must be hourly UTC boundaries")
        if (
            self.strategy.mode is not Mode.BACKTEST
            or self.strategy.strategy_id != self.run_id
            or self.risk.scope != self.run_id
        ):
            raise ValueError("strategy mode and strategy/risk scope must match the unique run ID")
        if len(self.risk.instruments) != 1 or self.risk.instruments[0].symbol != self.symbol:
            raise ValueError("v1 runs one instrument per accounting scope")
        if self.data_kind == "synthetic_csv" and (not self.csv_path or not self.csv_sha256):
            raise ValueError("synthetic CSV requires its path and immutable hash")
        if self.data_kind == "registered_hourly" and (self.csv_path or self.csv_sha256):
            raise ValueError("registered hourly inputs cannot substitute a CSV")
        if config_hash(self.fees) != config_hash(load_fees()):
            raise ValueError("backtests must retain accepted fee assumptions")
        return self

    def protocol(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"experiment_id"})
