"""Interactive, nonpromotable NSE development replay through the shared engine."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any, Literal, Self, cast
from uuid import uuid4

import numpy as np
import pandas as pd
from pydantic import Field, model_validator

from helios.alpha.evaluator import AlphaSeries
from helios.alpha.output import BoundedAlphaSeries, bound_alpha
from helios.backtest.equity import eligible_sessions, replay_session
from helios.common.config import HeliosConfig
from helios.common.lineage import PROJECT_ROOT, forget_git_state, git_commit, git_is_dirty
from helios.data.equities import sha256
from helios.equities.config import EquityResearchPolicy
from helios.equities.inputs import load_equity_inputs
from helios.equities.rebuild import UNIT_QUARANTINE

STRATEGIES = ("Trend following", "Mean reversion", "Long during session")
FIRST, LAST = date(2026, 1, 9), date(2026, 6, 30)


@dataclass(frozen=True)
class DatasetChoice:
    path: Path
    interval: Literal["1m", "1h"]
    symbols: tuple[str, ...]
    manifest_sha256: str


class NseOptions(HeliosConfig):
    symbol: str = Field(pattern=r"^[A-Z0-9&-]+$")
    start: date
    end: date
    strategy: Literal["Trend following", "Mean reversion", "Long during session"]
    lookback: int = Field(default=5, ge=1, le=60)
    capital: Decimal = Field(default=Decimal("100000"), ge=1000, le=10000000)
    allocation_pct: int = Field(default=10, ge=5, le=80)
    compare_costs: bool = True

    @model_validator(mode="after")
    def development_only(self) -> Self:
        if not FIRST <= self.start <= self.end <= LAST:
            raise ValueError(
                "Choose dates within the retained Jan 9–Jun 30, 2026 development window"
            )
        if (self.end - self.start).days >= 31:
            raise ValueError("Interactive runs support at most 31 calendar days at a time")
        if not self.capital.is_finite():
            raise ValueError("finite starting capital required")
        return self


def datasets(root: Path = PROJECT_ROOT) -> list[DatasetChoice]:
    choices = []
    for directory, interval in (("nifty50_repaired", "1m"), ("nifty50", "1h")):
        for path in sorted(
            (root / "data/equities" / directory).glob("*/manifest.json"), reverse=True
        ):
            manifest = json.loads(path.read_text())
            if interval == "1m":
                if manifest.get("version") != "nse_public_minutes_v2" or not manifest.get(
                    "complete"
                ):
                    continue
                symbols = [r["symbol"] for r in manifest["files"] if r.get("eligible_rows", 0) > 0]
            else:
                symbols = [r["symbol"] for r in manifest["files"] if r.get("interval") == "60m"]
            symbols = sorted(set(symbols) - UNIT_QUARANTINE)
            if symbols:
                choices.append(
                    DatasetChoice(
                        path.parent,
                        cast(Literal["1m", "1h"], interval),
                        tuple(symbols),
                        sha256(path),
                    )
                )
                break
    return choices


def template_signal(frame: pd.DataFrame, strategy: str, lookback: int) -> BoundedAlphaSeries:
    """Trailing closes reset each session; execution lag is supplied by the shared engine."""
    if strategy not in STRATEGIES or not 1 <= lookback <= 60:
        raise ValueError("known template and bounded lookback required")
    if frame.session_date.nunique() != 1 or not frame.open_time.is_monotonic_increasing:
        raise ValueError("one chronological session required")
    if frame.open_time.duplicated().any():
        raise ValueError("duplicate observed bar")
    close = frame.close.astype(float)
    known = pd.Series(np.isfinite(close.to_numpy()), index=close.index) & close.gt(0)
    if strategy == "Long during session":
        values = pd.Series(1.0, index=frame.index).where(known)
    else:
        past = close.shift(lookback)
        known &= known.rolling(lookback + 1).sum().eq(lookback + 1) & past.gt(0)
        direction = close.gt(past) if strategy == "Trend following" else close.lt(past)
        values = direction.astype(float).where(known)
    return bound_alpha(
        AlphaSeries(str(frame.symbol.iloc[0]), frame.open_time, values, known.astype(bool))
    )


def policy_for(dataset: DatasetChoice, options: NseOptions) -> EquityResearchPolicy:
    if dataset.interval == "1m":
        return EquityResearchPolicy(
            version="nse_minute_research_v2",
            interval="1m",
            session="reviewed_sessions_v2",
            commission_tax_proxy_bps=0,
            capital=options.capital,
            max_weight=Decimal(options.allocation_pct) / 100,
        )
    return EquityResearchPolicy(
        capital=options.capital, max_weight=Decimal(options.allocation_pct) / 100
    )


def _save(path: Path, value: Any) -> None:
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)


def _sources(destination: Path) -> dict[str, str]:
    hashes = {}
    for source in [
        *sorted((PROJECT_ROOT / "research/helios").rglob("*.py")),
        PROJECT_ROOT / "pyproject.toml",
        PROJECT_ROOT / "uv.lock",
    ]:
        name = source.relative_to(PROJECT_ROOT).as_posix()
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        body = source.read_bytes()
        with target.open("xb") as stream:
            stream.write(body)
        hashes[name] = hashlib.sha256(body).hexdigest()
    return hashes


def _verify_inputs(dataset: DatasetChoice, hashes: dict[str, str]) -> None:
    for name, expected in hashes.items():
        path = dataset.path / ("manifest.json" if name == "manifest" else name)
        if not path.resolve().is_relative_to(dataset.path.resolve()) or sha256(path) != expected:
            raise ValueError("dataset changed during the run; result is not accepted")


def run_backtest(
    dataset: DatasetChoice,
    options: NseOptions,
    *,
    output_root: Path | None = None,
    progress: Callable[[float, str], None] | None = None,
) -> Path:
    # Revalidate even a model_copy-created object before any price access.
    options = NseOptions.model_validate(options.model_dump())
    if options.symbol not in dataset.symbols or options.symbol in UNIT_QUARANTINE:
        raise ValueError(
            "Choose a company with screened observations; quarantined units are blocked"
        )
    if dataset.interval not in ("1m", "1h"):
        raise ValueError("only retained minute/hourly replay is supported")
    if sha256(dataset.path / "manifest.json") != dataset.manifest_sha256:
        raise ValueError("dataset manifest changed; refresh the dataset selection")
    policy = policy_for(dataset, options)
    inputs = load_equity_inputs(dataset.path, options.symbol, policy)
    _verify_inputs(dataset, inputs.hashes)
    selected = inputs.bars.session_date.between(str(options.start), str(options.end))
    expected = tuple(
        d for d in inputs.expected_sessions if str(options.start) <= d <= str(options.end)
    )
    chosen = replace(
        inputs, bars=inputs.bars.loc[selected].reset_index(drop=True), expected_sessions=expected
    )
    sessions, excluded = eligible_sessions(chosen, interval=dataset.interval)
    if not sessions:
        raise ValueError(
            "No complete screened sessions in this range. Choose another retained range"
        )
    signals = [template_signal(f, options.strategy, options.lookback) for f in sessions]
    run_id = "nse_ui_" + uuid4().hex[:20]
    output = (output_root or PROJECT_ROOT / "reports_out/nse_sandbox") / run_id
    output.mkdir(parents=True, exist_ok=False)
    forget_git_state()
    commit, dirty = git_commit(), git_is_dirty()
    source_hashes = _sources(output / "source")
    snapshot = hashlib.sha256(json.dumps(inputs.hashes, sort_keys=True).encode()).hexdigest()
    observed = pd.concat(sessions, ignore_index=True)
    observed.to_parquet(output / "observations.parquet", index=False)
    pd.concat(
        [
            pd.DataFrame(dict(open_time=a.open_time, value=a.values, available=a.available))
            for a in signals
        ],
        ignore_index=True,
    ).to_parquet(output / "signals.parquet", index=False)
    protocol = dict(
        purpose="interactive_nse_development_not_alpha_validation",
        run_id=run_id,
        created_at=datetime.now(UTC).isoformat(),
        options=options.model_dump(mode="json"),
        interval=dataset.interval,
        dataset=str(dataset.path),
        source_hashes=source_hashes,
        manifest_sha256=dataset.manifest_sha256,
        input_hashes=inputs.hashes,
        code_commit=commit,
        dirty=dirty,
        snapshot_id=snapshot,
        policy=policy.model_dump(mode="json"),
        cash_carries_between_flat_sessions=True,
        expected_sessions=list(expected),
        excluded_sessions=excluded,
        observations_sha256=sha256(output / "observations.parquet"),
        signals_sha256=sha256(output / "signals.parquet"),
        test_accesses=0,
        registry_writes=0,
        actual_orders=0,
        eligible=False,
    )
    _save(output / "protocol.json", protocol)  # frozen before strategy P&L
    scenarios = {}
    multipliers = (1, 2) if options.compare_costs else (1,)
    try:
        for multiplier in multipliers:
            cash, fees, slippage = options.capital, Decimal(0), Decimal(0)
            curve: list[dict[str, Any]] = []
            fills: list[dict[str, Any]] = []
            adjustments: list[dict[str, Any]] = []
            daily: list[dict[str, Any]] = []
            orders: list[dict[str, Any]] = []
            with localcontext() as context:
                context.prec = 100
                for i, (frame, alpha) in enumerate(zip(sessions, signals, strict=True)):
                    session_policy = policy.model_copy(update={"capital": cash})
                    replay = replay_session(
                        frame,
                        alpha,
                        session_policy,
                        snapshot_id=snapshot,
                        alpha_id="nse_ui_template",
                        code_commit=commit,
                        multiplier=multiplier,
                    )
                    before = cash
                    cash = replay.trace.snapshots[-1].equity
                    fees += Decimal(replay.fees)
                    opens = dict(zip(frame.open_time, frame.open.astype(str), strict=True))
                    for fill in replay.fills:
                        cost = abs(
                            Decimal(fill["price"]) - Decimal(opens[fill["timestamp"]])
                        ) * Decimal(fill["quantity"])
                        slippage += cost
                    curve.extend(
                        dict(timestamp=p["timestamp"], equity=p["equity"]) for p in replay.snapshots
                    )
                    fills.extend(replay.fills)
                    adjustments.extend(replay.fee_adjustments)
                    orders.extend(x.model_dump(mode="json") for x in replay.trace.orders)
                    daily.append(
                        dict(
                            day=replay.day,
                            start_cash=str(before),
                            end_cash=str(cash),
                            net_pnl=str(cash - before),
                            net_return=replay.net_return,
                            fees=replay.fees,
                            fills=replay.n_fills,
                            terminal_inventory=0,
                        )
                    )
                    if progress:
                        completed = (multiplier - 1) * len(sessions) + i + 1
                        progress(
                            completed / (len(sessions) * len(multipliers)),
                            f"{'Normal' if multiplier == 1 else 'Doubled'} costs · "
                            f"{i + 1}/{len(sessions)} sessions",
                        )
            values = np.array([float(options.capital), *[float(p["equity"]) for p in curve]])
            returns = np.array([d["net_return"] for d in daily])
            sd = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
            scenarios[str(multiplier)] = dict(
                summary=dict(
                    final_equity=str(cash),
                    net_pnl=str(cash - options.capital),
                    net_return=float(cash / options.capital - 1),
                    fees=str(fees),
                    slippage=str(slippage),
                    gross_pnl=str(cash - options.capital + fees + slippage),
                    max_drawdown=float(np.min(values / np.maximum.accumulate(values) - 1)),
                    sharpe=None if sd == 0 else float(returns.mean() / sd * np.sqrt(252)),
                    sessions=len(sessions),
                    fills=len(fills),
                    orders=len(orders),
                ),
                daily=daily,
                equity=curve,
                fills=fills,
                fee_adjustments=adjustments,
                orders=orders,
            )
        _verify_inputs(dataset, inputs.hashes)
        for name, digest in source_hashes.items():
            if sha256(PROJECT_ROOT / name) != digest:
                raise ValueError("source changed during replay; result is not accepted")
        _save(
            output / "result.json",
            dict(
                run_id=run_id,
                protocol_sha256=sha256(output / "protocol.json"),
                scenarios=scenarios,
                eligible=False,
                test_accesses=0,
            ),
        )
        _save(
            output / "artifact_hashes.json",
            {p.name: sha256(p) for p in output.iterdir() if p.is_file()},
        )
    except Exception as exc:
        _save(output / "failure.json", dict(status="FAILED", error_type=type(exc).__name__))
        raise
    return output


def read_run(directory: Path) -> tuple[dict[str, Any], dict[str, Any], pd.DataFrame]:
    hashes = json.loads((directory / "artifact_hashes.json").read_text())
    for name in ("protocol.json", "result.json", "observations.parquet", "signals.parquet"):
        if sha256(directory / name) != hashes[name]:
            raise ValueError("retained backtest artifact checksum mismatch")
    protocol = json.loads((directory / "protocol.json").read_text())
    result = json.loads((directory / "result.json").read_text())
    if (
        result["protocol_sha256"] != hashes["protocol.json"]
        or result["eligible"]
        or result["test_accesses"]
    ):
        raise ValueError("interactive result lineage mismatch")
    return protocol, result, pd.read_parquet(directory / "observations.parquet")
