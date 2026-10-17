"""NSE adapter: shared formulas, execution engine, metrics, gates and result registry."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, replace
from decimal import ROUND_HALF_UP, Decimal, localcontext
from pathlib import Path
from typing import Any, Literal

import numpy as np
from sqlalchemy import Engine, text

from helios.alpha.output import evaluate_definition
from helios.backtest.equity import eligible_sessions, replay_session
from helios.common.config import config_hash, load_config
from helios.common.lineage import PROJECT_ROOT, RunContext
from helios.common.project_config import GatesConfig
from helios.equities.config import EquityResearchPolicy
from helios.equities.inputs import EquityInputs
from helios.equities.model import EquityModel
from helios.registry.api import RegistryError
from helios.registry.experiments import require_open_experiment
from helios.registry.gates import get_gate_config
from helios.registry.results import AlphaResult, Split, Status, record_result
from helios.sim.fitness import fitness
from helios.sim.gates import GateOutcome, gate_decisions
from helios.sim.metrics import return_metrics
from helios.sim.validity import InvalidReason, ValidityConfig, alpha_validity

GATES_PATH = PROJECT_ROOT / "configs/equities/gates_v1.yaml"


@dataclass(frozen=True)
class EquityEvaluationContext:
    policy: EquityResearchPolicy
    inputs: EquityInputs
    snapshot_id: str
    model: EquityModel
    source_hashes: dict[str, str]


def evaluate_equity(
    alpha_id: str,
    split: Split,
    experiment_id: int,
    *,
    engine: Engine,
    context: EquityEvaluationContext,
    output_dir: Path,
    reported: bool,
) -> AlphaResult:
    from helios.sim.evaluate import _definition

    if split is not Split.VALID:
        raise RegistryError("equity research currently authorizes VALID only; TEST stays sealed")
    started = time.monotonic()
    policy, source = context.policy, context.inputs
    gates = load_config(GATES_PATH, GatesConfig)
    with engine.begin() as connection:
        definition = _definition(connection, alpha_id, 1)
        experiment = require_open_experiment(connection, experiment_id)
        if experiment.snapshot_id != context.snapshot_id or experiment.params != dict(
            market="nse_cash",
            symbol=source.symbol,
            alpha_id=alpha_id,
            policy_hash=config_hash(policy),
            model_hash=context.model.model_hash,
            calibration_hash=context.model.calibration_hash,
            source_hashes=context.source_hashes,
        ):
            raise RegistryError("equity evaluation differs from the preregistered protocol")
        if connection.execute(
            text("SELECT count(*) FROM alpha_results WHERE experiment_id=:id"),
            dict(id=experiment_id),
        ).scalar_one():
            raise RegistryError("this immutable equity attempt already has a result")
        if get_gate_config(connection, gates.version).config_hash != config_hash(gates):
            raise RegistryError("equity gate configuration mismatch")
        if (
            definition.model_ref is not None
            and definition.model_ref != "sha256:" + context.model.model_hash
        ):
            raise RegistryError("registered equity model reference mismatch")
    lineage = RunContext.capture(policy, context.snapshot_id, policy.seed, reported=reported)
    alpha = (
        evaluate_definition(definition, source.features, interval="1h")
        if definition.expression is not None
        else context.model.alpha(source.features, policy)
    )
    sessions, excluded = eligible_sessions(source)
    # Performance is explicitly conditional on this ex-post complete-session cohort.
    # This is a data-quality study; G7 prohibits promotion for the current vendor data.
    opportunity_times: set[int] = set()
    for frame in sessions:
        opportunity_times.update(int(value) for value in frame.open_time.iloc[:5])
    keep = alpha.open_time.isin(opportunity_times) & alpha.available
    subset = replace(
        alpha,
        open_time=alpha.open_time.loc[keep].reset_index(drop=True),
        values=alpha.values.loc[keep].reset_index(drop=True),
        available=alpha.available.loc[keep].reset_index(drop=True),
    )
    validity = alpha_validity(subset, config=ValidityConfig(min_periods=2))
    reasons = list(validity.reasons)
    if len(sessions) < policy.minimum_sessions:
        reasons.append(InvalidReason.TOO_FEW_PERIODS)
    valid = not reasons
    protocol: dict[str, Any] = dict(
        market="nse_cash",
        quote_asset="INR",
        policy=policy.model_dump(mode="json"),
        definition=definition.model_dump(mode="json"),
        gates=gates.model_dump(mode="json"),
        execution=(
            "shared strategy/risk/OMS/venue/ledger; next observed open; whole shares; long-only"
        ),
        accounting="independent flat-to-flat sessions; arithmetic P&L / fixed starting capital",
        turnover="observed traded notional / capital / six scheduled full hours per session",
        coverage="conditional on complete observed normal sessions, selected ex-post",
        source_hashes=context.source_hashes,
        input_hashes=source.hashes,
        model_hash=context.model.model_hash,
        calibration_hash=context.model.calibration_hash,
        test_access=False,
    )
    daily: list[dict[str, Any]] = []
    stress: list[float] = []
    fills: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    turn, fee_total = [], Decimal(0)
    metrics = stressed_metrics = None
    fit_value = fraction = drawdown = hit_rate = None
    months: list[dict[str, Any]] = []
    if valid:
        for frame in sessions:
            base = replay_session(
                frame,
                alpha,
                policy,
                snapshot_id=context.snapshot_id,
                alpha_id=alpha_id,
                code_commit=lineage.code_commit,
                model_hash=context.model.model_hash if definition.model_ref else None,
            )
            doubled = replay_session(
                frame,
                alpha,
                policy,
                snapshot_id=context.snapshot_id,
                alpha_id=alpha_id,
                code_commit=lineage.code_commit,
                multiplier=gates.cost_stress_multiplier,
                model_hash=context.model.model_hash if definition.model_ref else None,
            )
            daily.append(
                dict(
                    day=base.day,
                    open_time=int(frame.open_time.iloc[0]),
                    net_return=base.net_return,
                    turnover=base.turnover,
                    fees=base.fees,
                    n_fills=base.n_fills,
                )
            )
            stress.append(doubled.net_return)
            turn.append(base.turnover / 6)
            fee_total += Decimal(base.fees)
            fills.extend(base.fills)
            snapshots.extend(base.snapshots)
        returns = np.asarray([row["net_return"] for row in daily], dtype=float)
        metrics = return_metrics(returns, periods_per_year=policy.trading_sessions_per_year)
        stressed_metrics = return_metrics(stress, periods_per_year=policy.trading_sessions_per_year)
        fit_value = fitness(
            metrics.annual_sharpe,
            metrics.annual_return,
            float(np.mean(turn)),
            floor=gates.fitness_turnover_floor,
        )
        cumulative = np.cumsum(returns)
        drawdown = float(np.min(cumulative - np.maximum.accumulate(np.r_[0.0, cumulative])[1:]))
        hit_rate = float(np.mean(returns > 0))
        month_keys = np.asarray([str(row["day"])[:7] for row in daily])
        for month in sorted(set(month_keys)):
            selected = returns[month_keys == month]
            monthly = return_metrics(selected, periods_per_year=policy.trading_sessions_per_year)
            months.append(
                dict(
                    month=str(month),
                    metrics=asdict(monthly),
                    has_gaps=any(row["day"].startswith(month) for row in excluded),
                )
            )
        fraction = float(np.mean([row["metrics"]["total_return"] > 0 for row in months]))
    report = gate_decisions(
        sharpe=None if metrics is None else metrics.annual_sharpe,
        fitness=fit_value,
        turnover=float(np.mean(turn)) if turn else None,
        split=split,
        positive_fraction=fraction,
        cost_stress_sharpe=None if stressed_metrics is None else stressed_metrics.annual_sharpe,
        gates=gates,
    )
    coverage = len(sessions) / len(source.expected_sessions) if source.expected_sessions else 0.0
    outcomes = report.outcomes + (
        GateOutcome(
            "G7",
            False,
            False,
            True,
            "source_validation_required",
            "current-universe survivorship bias; vendor/calendar/corporate actions unverified",
        ),
        GateOutcome(
            "G8",
            coverage >= policy.minimum_coverage,
            coverage,
            policy.minimum_coverage,
            ">=",
            None
            if coverage >= policy.minimum_coverage
            else "insufficient_complete_session_coverage",
        ),
    )
    if not valid:
        outcomes = tuple(replace(gate, passed=False, reason="invalid_alpha") for gate in outcomes)
    report_status: Literal["REJECTED", "INVALID"] = "REJECTED" if valid else "INVALID"
    status = Status(report_status)
    validity_evidence = asdict(validity) | dict(
        status="VALID" if valid else "INVALID",
        reasons=[reason.value for reason in reasons],
        n_rows=len(subset.values),
        n_sessions=len(sessions),
    )
    evidence: dict[str, Any] = dict(
        status=status.value,
        snapshot_id=context.snapshot_id,
        market="nse_cash",
        validity=validity_evidence,
        protocol=protocol,
        gates=asdict(
            replace(report, status=report_status, outcomes=outcomes, invalid_reasons=tuple(reasons))
        ),
        source=asdict(lineage),
        source_hashes=context.source_hashes,
        diagnostics={} if metrics is None else {"base": {"metrics": asdict(metrics)}},
        stability={"months": months, "regimes": []},
        series=daily,
        stress_session_returns=stress,
        costs={"points": []},
        fills=fills,
        ledger_snapshots=snapshots,
        coverage=dict(
            expected=len(source.expected_sessions),
            complete=len(sessions),
            fraction=coverage,
            excluded=excluded,
        ),
        fees_total_inr=str(fee_total),
        test_access=False,
        is_simulated=True,
        notice="NSE conditional complete-session development benchmark; proxy costs. "
        "Missing sessions are excluded, not zero-filled. No promotion eligibility.",
    )
    if metrics is not None and stressed_metrics is not None:
        evidence["costs"]["points"] = [
            dict(multiplier=value, total_cost=None, metrics={"metrics": asdict(measured)})
            for value, measured in (
                (1.0, metrics),
                (gates.cost_stress_multiplier, stressed_metrics),
            )
        ]
    run_id = str(uuid.uuid4())
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact = output_dir / f"{run_id}.json"
    encoded = json.dumps(evidence, default=str, sort_keys=True, allow_nan=False).encode()
    with artifact.open("xb") as handle:
        handle.write(encoded)

    def decimal(value: float | None) -> Decimal | None:
        if value is None:
            return None
        with localcontext() as context:
            context.prec = 50
            return Decimal(str(value)).quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP)

    result = AlphaResult(
        run_id=run_id,
        experiment_id=experiment_id,
        alpha_id=alpha_id,
        version=1,
        split=split,
        snapshot_id=context.snapshot_id,
        gate_config_id=gates.version,
        sharpe=decimal(None if metrics is None else metrics.annual_sharpe),
        annual_return=decimal(None if metrics is None else metrics.annual_return),
        turnover=decimal(float(np.mean(turn)) if turn else None),
        fitness=decimal(fit_value),
        periods=0 if metrics is None else metrics.n_periods,
        max_drawdown=decimal(drawdown),
        hit_rate=decimal(hit_rate),
        cost_stress_sharpe=decimal(
            None if stressed_metrics is None else stressed_metrics.annual_sharpe
        ),
        stability_positive_fraction=decimal(fraction),
        gate_results={gate.gate: gate.passed for gate in outcomes},
        status=status,
        code_commit=lineage.code_commit,
        dirty=lineage.dirty,
        seed=policy.seed,
        config_hash=hashlib.sha256(json.dumps(protocol, sort_keys=True).encode()).hexdigest(),
        runtime_seconds=decimal(time.monotonic() - started),
        evaluation_json=dict(
            status=status.value,
            market="nse_cash",
            artifact=str(artifact),
            artifact_sha256=hashlib.sha256(encoded).hexdigest(),
            validity=validity_evidence,
            protocol=protocol,
        ),
    )
    with engine.begin() as connection:
        return record_result(connection, result)
