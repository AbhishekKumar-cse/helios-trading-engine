"""Runnable synthetic sandbox using the real backtest stack, without registry writes."""

import csv
import json
import random
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field

from helios.backtest.config import BacktestConfig
from helios.backtest.engine import simulate
from helios.backtest.inputs import load_inputs
from helios.backtest.runner import BacktestArtifact
from helios.common.config import HeliosConfig
from helios.common.lineage import RunContext, forget_git_state
from helios.common.types import Mode
from helios.data.binance import sha256_file
from helios.data.snapshots import SnapshotFile, compute_snapshot_id
from helios.registry.api import AlphaDefinition
from helios.registry.results import Split
from helios.sim.loss_risk import DailyRiskLimits, RiskTrip
from helios.sim.portfolio_risk import PositionLimits
from helios.sim.strategy import BarStrategyConfig

ROOT = Path(__file__).resolve().parents[3]
HOUR = 3_600_000_000
START = 1_609_459_200_000_000  # Explicit synthetic timeline: 2021-01-01 UTC.
STRATEGIES = ("Trend following", "Mean reversion", "Buy and hold")
SCENARIOS = ("Trend and pullback", "Choppy range", "Sell-off and recovery")


class DemoOptions(HeliosConfig):
    strategy: Literal["Trend following", "Mean reversion", "Buy and hold"] = "Trend following"
    scenario: Literal["Trend and pullback", "Choppy range", "Sell-off and recovery"] = (
        "Trend and pullback"
    )
    capital: int = Field(default=10000, ge=100, le=1000000)
    allocation_pct: int = Field(default=25, ge=5, le=80)
    daily_loss_pct: float = Field(default=5, ge=0.1, le=20, allow_inf_nan=False)
    lookback: int = Field(default=6, ge=1, le=24)
    bars: Literal[96, 168, 336] = 168
    seed: int = Field(default=42, ge=0, le=2**32 - 1)


class DemoTripStore:
    """Per-run latch; intentionally never connects to the research database."""

    def __init__(self) -> None:
        self.events: list[RiskTrip] = []

    def is_tripped(self, scope: str) -> bool:
        return any(event.scope == scope for event in self.events)

    def trip(self, event: RiskTrip) -> None:
        if not self.is_tripped(event.scope):
            self.events.append(event)


def synthetic_rows(options: DemoOptions) -> list[dict[str, str | int]]:
    rng = random.Random(options.seed)
    closes: list[Decimal] = []
    price = Decimal("40000")
    rows: list[dict[str, str | int]] = []
    for index in range(options.bars):
        if options.scenario == "Choppy range":
            drift = (40000 - float(price)) / 40000 * 0.12
        elif options.scenario == "Sell-off and recovery":
            drift = (
                -0.10
                if index == options.bars // 2
                else (-0.001 if index < options.bars * 0.65 else 0.003)
            )
        else:
            drift = (
                0.0015
                if index < options.bars * 0.4
                else (-0.0018 if index < options.bars * 0.7 else 0.002)
            )
        closed = max(Decimal("1000"), price * Decimal(str(1 + drift + rng.gauss(0, 0.006))))
        closed = closed.quantize(Decimal("0.000001"))
        spread = Decimal(str(rng.uniform(0.0005, 0.004)))
        high = (max(price, closed) * (1 + spread)).quantize(Decimal("0.000001"))
        low = (min(price, closed) * (1 - spread)).quantize(Decimal("0.000001"))
        closes.append(closed)
        signal = ""
        if index >= options.lookback:
            direction = (closed > closes[index - options.lookback]) - (
                closed < closes[index - options.lookback]
            )
            signal = str(
                1
                if options.strategy == "Buy and hold"
                else (-direction if options.strategy == "Mean reversion" else direction)
            )
        rows.append(
            dict(
                bar=index,
                open=str(price),
                high=str(high),
                low=str(low),
                close=str(closed),
                volume=str(rng.randint(50, 500)),
                decision_alpha=signal,
            )
        )
        price = closed
    return rows


@dataclass(frozen=True)
class DemoRun:
    options: DemoOptions
    artifact: BacktestArtifact
    trips: tuple[RiskTrip, ...]
    path: Path

    def export(self) -> str:
        return json.dumps(
            dict(
                purpose="synthetic_interactive_sandbox_not_research",
                options=self.options.model_dump(mode="json"),
                artifact=self.artifact.model_dump(mode="json"),
                trips=[event.model_dump(mode="json") for event in self.trips],
            ),
            indent=2,
        )


def run_demo(options: DemoOptions, *, root: Path | None = None) -> DemoRun:
    run_id = "demo_" + uuid4().hex[:20]
    destination = (ROOT / "reports_out/sandbox" if root is None else root) / run_id
    destination.mkdir(parents=True, exist_ok=False)
    path = destination / "bars.csv"
    rows = synthetic_rows(options)
    with path.open("x", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    digest = sha256_file(path)
    snapshot = compute_snapshot_id([SnapshotFile(str(path), digest, path.stat().st_size)])
    capital = Decimal(options.capital)
    weight = Decimal(options.allocation_pct) / 100
    notional = capital * weight
    config = BacktestConfig(
        run_id=run_id,
        alpha_id="sandbox_demo_v1",
        snapshot_id=snapshot,
        seed=options.seed,
        symbol="BTCUSDT",
        split=Split.TRAIN,
        data_kind="synthetic_csv",
        csv_path=str(path),
        csv_sha256=digest,
        start_us=START,
        end_us=START + options.bars * HOUR,
        strategy=BarStrategyConfig(
            capital=capital,
            max_weight=weight,
            strategy_id=run_id,
            rebalance_threshold=Decimal("0.02"),
            mode=Mode.BACKTEST,
        ),
        risk=DailyRiskLimits(
            scope=run_id,
            daily_loss_limit=capital * Decimal(str(options.daily_loss_pct)) / 100,
            max_gross_exposure=notional * Decimal("1.5"),
            instruments=(
                PositionLimits(
                    symbol="BTCUSDT",
                    max_order_notional=notional * Decimal("2.5"),
                    max_position_notional=notional * Decimal("1.5"),
                    price_band_fraction=Decimal("0.1"),
                    median_window=1,
                    max_price_age_us=0,
                ),
            ),
        ),
    )
    forget_git_state()
    context = RunContext.capture(config, snapshot, options.seed, reported=False)
    definition = AlphaDefinition(
        alpha_id=config.alpha_id,
        version=1,
        name="Interactive synthetic sandbox",
        feature_set_version="sandbox_synthetic_v1",
        horizon_family="H-HOURLY",
        horizon_periods=1,
        author="local_sandbox",
        code_commit=context.code_commit,
        spec=dict(synthetic_csv_sha256=digest, is_synthetic=True),
    )
    inputs = load_inputs(config, definition, context)
    store = DemoTripStore()
    trace = simulate(config, inputs.bars, inputs.signals, store)
    artifact = BacktestArtifact(
        config=config,
        context=context,
        input_sha256=inputs.sha256,
        bars=inputs.bars,
        signals=inputs.signals,
        trace=trace,
    )
    run = DemoRun(options, artifact, tuple(store.events), destination / "simulation.json")
    with run.path.open("x") as handle:
        handle.write(run.export() + "\n")
    return run
