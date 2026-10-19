"""Causal opening observations and cost accounting for longer-horizon TRAIN screens.

These are conditional price-proxy research helpers, not execution certification
or a substitute for the shared backtester and its unchanged promotion gates.
"""

from datetime import date
from decimal import Decimal, localcontext

import numpy as np
import pandas as pd

from helios.equities.charges import ChargeTrade, estimate_intraday_charges

FEATURES = (
    "move_5",
    "move_15",
    "move_30",
    "recent_5",
    "recent_15",
    "range_30",
    "location_30",
    "volatility_30",
    "volume_ratio",
    "up_fraction",
)
EXITS = {"m60": 90, "m120": 150, "session_close": 374}
HURDLE = 0.0021


def opening_features(bars: pd.DataFrame) -> dict[str, float]:
    """Only the first 30 completed minutes can affect this observation."""
    if len(bars) < 30:
        raise ValueError("30 completed bars required")
    part = bars.iloc[:30]
    prices = part[["open", "high", "low", "close", "volume"]].to_numpy(dtype=float)
    if not np.isfinite(prices).all() or (prices <= 0).any():
        raise ValueError("opening features unavailable")
    opening, close = float(part.open.iloc[0]), part.close.to_numpy(dtype=float)
    high, low = float(part.high.max()), float(part.low.min())
    if high <= low:
        raise ValueError("opening range unavailable")
    values = (
        close[4] / opening - 1,
        close[14] / opening - 1,
        close[29] / opening - 1,
        close[29] / close[24] - 1,
        close[29] / close[14] - 1,
        (high - low) / opening,
        (close[29] - low) / (high - low),
        np.std(np.diff(np.log(close)), ddof=0),
        float(part.volume.iloc[-5:].mean()) / float(part.volume.iloc[:5].mean()),
        float(np.mean(np.diff(close) > 0)),
    )
    return dict(zip(FEATURES, map(float, values), strict=True))


def forward_return(bars: pd.DataFrame, exit_slot: int) -> float:
    """Next opening after first30 close to the preregistered later opening."""
    if len(bars) != 375 or exit_slot not in EXITS.values():
        raise ValueError("one full session and a frozen exit required")
    if bars.session_date.nunique() != 1 or not (bars.open_time.diff().iloc[1:] == 60_000_000).all():
        raise ValueError("label cannot cross a session or missing minute")
    entry, exit_ = float(bars.open.iloc[30]), float(bars.open.iloc[exit_slot])
    if not np.isfinite([entry, exit_]).all() or min(entry, exit_) <= 0:
        raise ValueError("label unavailable")
    return exit_ / entry - 1


def cost_screen(
    day: date,
    symbol: str,
    decision_close: Decimal,
    entry: Decimal,
    exit_: Decimal,
    *,
    active: bool,
    multiplier: int,
) -> dict[str, str]:
    if multiplier not in (1, 2):
        raise ValueError("only frozen normal and doubled scenarios are supported")
    if any(not x.is_finite() or x <= 0 for x in (decision_close, entry, exit_)):
        raise ValueError("positive observed prices required")
    with localcontext() as context:
        context.prec = 100
        quantity = Decimal("50000") // decision_close if active else Decimal(0)
        gross = slippage = fees = net = Decimal(0)
        if active:
            if quantity < 1:
                raise ValueError("no whole share fits the frozen budget")
            adverse = Decimal(".0005") * multiplier
            buy, sell = entry * (1 + adverse), exit_ * (1 - adverse)
            charges = [
                ChargeTrade(day, symbol, "entry", "BUY", quantity, buy),
                ChargeTrade(day, symbol, "exit", "SELL", quantity, sell),
            ]
            fees = estimate_intraday_charges(charges).total * multiplier
            if quantity * buy + fees >= Decimal("100000"):
                raise ValueError("entry cannot be funded by the independent daily account")
            gross = quantity * (exit_ - entry)
            slippage = quantity * (buy - entry + exit_ - sell)
            net = quantity * (sell - buy) - fees
            assert abs(net - (gross - slippage - fees)) < Decimal("1e-70")
        return {
            k: str(v)
            for k, v in dict(
                quantity=quantity,
                gross=gross,
                slippage=slippage,
                fees=fees,
                net=net,
            ).items()
        }
