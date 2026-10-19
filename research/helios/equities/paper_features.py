"""Causal daily history and binary state features for the three paper prototypes.

The source cohort remains explicitly retrospective and conditionally screened.
Missing, quarantined and special sessions invalidate lookbacks; no backfilling.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from helios.data.equities import sha256
from helios.equities.config import EquityResearchPolicy
from helios.equities.inputs import EquityInputs, load_equity_inputs
from helios.equities.paper_signals import NAMES, Setup, decisions
from helios.equities.rebuild import membership, verified_file
from helios.features.runner import FeatureFrame

FEATURE_SET = "nse_paper_minute_features_v1"
EXECUTION = "paper_state_change_v1"


def feature_digest(features: FeatureFrame) -> str:
    payload = pd.concat(
        [features.open_time, features.values, features.available.add_suffix("_available")], axis=1
    ).to_json(orient="split", double_precision=15)
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True)
class DaySummary:
    day: str
    high: float
    low: float
    close: float
    opening_volume: float
    noise: NDArray[np.float64] | None


def full_session(frame: pd.DataFrame) -> bool:
    """Same strict normal-session screen used by the frozen exploratory study."""
    if len(frame) != 375 or not frame.research_eligible.all():
        return False
    clock = frame.timestamp.dt.tz_convert("Asia/Kolkata")
    return bool(
        set(frame.screen_status) == {"PASS_SCALE_SCREEN"}
        and (frame.volume > 0).all()
        and not frame.open_time.duplicated().any()
        and (clock.dt.hour * 60 + clock.dt.minute).tolist() == list(range(555, 930))
        and (clock.dt.second == 0).all()
        and (clock.dt.microsecond == 0).all()
        and (frame.low <= frame[["open", "close"]].min(axis=1)).all()
        and (frame.high >= frame[["open", "close"]].max(axis=1)).all()
        and np.isfinite(frame[["open", "high", "low", "close", "volume"]]).all().all()
        and (frame[["open", "high", "low", "close"]] > 0).all().all()
    )


def causal_setups(
    symbol: str,
    bars: pd.DataFrame,
    calendar: dict[str, Any],
    *,
    include_noise: bool,
) -> tuple[dict[str, Setup | None], list[dict[str, Any]]]:
    """At most the previous 15 scheduled observations; holes remain holes."""
    grouped = {str(d): p.sort_values("open_time") for d, p in bars.groupby("session_date")}
    history: deque[DaySummary | None] = deque(maxlen=15)
    previous: DaySummary | None = None
    setups, audit = {}, []
    for day in sorted(calendar):
        if not membership(symbol, day)[1]:
            history.clear()
            previous = None
            continue
        part = grouped.get(day)
        if (
            part is None
            or calendar[day]["slots"] != 375
            or calendar[day]["open_minute"] != 555
            or not full_session(part)
        ):
            history.append(None)
            previous = None
            continue
        setup = None if previous is None else Setup(previous.close)
        if setup is not None and len(history) == 15 and all(h is not None for h in history):
            prior = [h for h in history if h is not None]
            prior_days = [h.day for h in prior]
            if len(set(prior_days)) != 15 or max(prior_days) >= day:
                raise ValueError("noncausal paper history")
            setup.opening_rvol = float(part.volume.iloc[:5].sum()) / float(
                np.mean([h.opening_volume for h in prior[1:]])
            )
            setup.atr14 = float(
                np.mean(
                    [
                        max(h.high - h.low, abs(h.high - p.close), abs(h.low - p.close))
                        for p, h in zip(prior[:-1], prior[1:], strict=True)
                    ]
                )
            )
            if include_noise:
                setup.noise14 = np.mean([h.noise for h in prior[1:]], axis=0)
            audit.append(dict(symbol=symbol, day=day, prior_days=prior_days))
        setups[day] = setup
        previous = DaySummary(
            day,
            float(part.high.max()),
            float(part.low.min()),
            float(part.close.iloc[-1]),
            float(part.volume.iloc[:5].sum()),
            abs(part.close.to_numpy(dtype=float) / float(part.open.iloc[0]) - 1)
            if include_noise
            else None,
        )
        history.append(previous)
    return setups, audit


def signal_frame(name: str, source: EquityInputs, setups: dict[str, Setup | None]) -> FeatureFrame:
    if name not in NAMES:
        raise ValueError("unknown paper candidate")
    values = pd.Series(np.nan, index=source.bars.index, name=name, dtype=float)
    available = pd.Series(False, index=source.bars.index, name=name)
    for day, frame in source.bars.groupby("session_date", sort=True):
        setup = setups.get(str(day))
        if (
            not full_session(frame)
            or setup is None
            or (name != "closing_momentum" and setup.noise14 is None)
        ):
            continue
        values.loc[frame.index] = 0.0
        available.loc[frame.index] = True
        selected = decisions(name, frame.reset_index(drop=True), setup)
        if selected is not None:
            entry, exit_ = selected
            if not 0 <= entry < exit_ <= 373:
                raise ValueError("invalid close-decision schedule")
            values.loc[frame.index[entry:exit_]] = 1.0
    return FeatureFrame(
        source.symbol, source.bars.open_time.copy(), values.to_frame(), available.to_frame()
    )


def prepare_inputs(
    snapshot: Path, symbols: tuple[str, ...], policy: EquityResearchPolicy
) -> tuple[dict[str, dict[str, EquityInputs]], dict[str, Any]]:
    if policy.version != "nse_minute_research_v2":
        raise ValueError("paper prototypes require the conditional v2 source")
    manifest = json.loads((snapshot / "manifest.json").read_text())
    if manifest["test_access"] or manifest["g7_eligible"] or not manifest["complete"]:
        raise ValueError("expected a complete conditional TEST-sealed snapshot")
    calendar = json.loads(
        verified_file(snapshot, "sessions.json", manifest["sessions_sha256"]).read_text()
    )
    calendar = {d: s for d, s in calendar.items() if d <= policy.valid_end.isoformat()}
    cohort = sorted(r["symbol"] for r in manifest["files"] if r["eligible_rows"] > 0)
    if not symbols or len(set(symbols)) != len(symbols) or not set(symbols) <= set(cohort):
        raise ValueError("execution symbols must be distinct screened historical companies")
    setups_by_symbol, ranking, history_audit, input_hashes = {}, defaultdict(list), [], {}
    for item in sorted(manifest["files"], key=lambda x: x["symbol"]):
        symbol = item["symbol"]
        if symbol not in cohort:
            continue
        path = verified_file(snapshot, item["path"], item["sha256"])
        bars = pd.read_parquet(path, filters=[("session_date", "<=", policy.valid_end.isoformat())])
        if (
            bars.empty
            or set(bars.symbol) != {symbol}
            or not bars.session_date.between("2025-01-01", policy.valid_end.isoformat()).all()
        ):
            raise ValueError("paper source identity/split mismatch")
        setups, audit = causal_setups(symbol, bars, calendar, include_noise=symbol in symbols)
        input_hashes[symbol] = sha256(path)
        for day, setup in setups.items():
            if setup is not None and setup.opening_rvol is not None:
                ranking[day].append((setup.opening_rvol, symbol))
        if symbol in symbols:
            setups_by_symbol[symbol] = setups
            history_audit.extend(audit)
    for day, candidates in ranking.items():
        selected = {s for _, s in sorted(candidates, key=lambda x: (-x[0], x[1]))[:20]}
        for symbol, setups in setups_by_symbol.items():
            setup = setups.get(day)
            if setup is not None:
                setup.top20 = symbol in selected
    answer: dict[str, dict[str, EquityInputs]] = {}
    for symbol in symbols:
        source = load_equity_inputs(snapshot, symbol, policy)
        answer[symbol] = {}
        for name in NAMES:
            features = signal_frame(name, source, setups_by_symbol[symbol])
            hashes = source.hashes | {"paper_signal_sha256": feature_digest(features)}
            answer[symbol][name] = replace(source, features=features, hashes=hashes)
    return answer, dict(
        version=FEATURE_SET,
        execution_policy=EXECUTION,
        ranking_universe=cohort,
        ranking_available_after="first five completed minute bars",
        source_files=input_hashes,
        history_windows=history_audit,
        scope="conditional ex-post cohort; prior TRAIN/VALID exposure; no fresh OOS claim",
        test_access=False,
        g7_eligible=False,
    )
