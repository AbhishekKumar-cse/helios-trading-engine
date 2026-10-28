"""Read-only NSE playback over retained observations and actual simulated receipts."""

from decimal import Decimal, localcontext
from typing import Any

import pandas as pd


def replay_view(
    protocol: dict[str, Any], result: dict[str, Any], bars: pd.DataFrame, cursor: int
) -> dict[str, Any]:
    account = result["scenarios"]["1"]
    if not 0 <= cursor <= len(bars) or len(account["equity"]) != len(bars):
        raise ValueError("replay cursor or retained observation/snapshot alignment invalid")
    points = account["equity"][:cursor]
    start = int(bars.open_time.iloc[0])
    clock = int(points[-1]["timestamp"]) if points else start - 1
    # A completed bar is observed before the next opening at the same clock.
    fills = [f for f in account["fills"] if int(f["timestamp"]) < clock]
    charges = [c for c in account["fee_adjustments"] if int(c["timestamp"]) <= clock]
    seen = bars.iloc[:cursor]
    candles = [
        dict(
            time=pd.to_datetime(r["open_time"], unit="us", utc=True).isoformat(),
            open=float(r["open"]),
            high=float(r["high"]),
            low=float(r["low"]),
            close=float(r["close"]),
            direction="Up" if r["close"] >= r["open"] else "Down",
        )
        for r in seen.to_dict("records")
    ]
    capital = Decimal(protocol["options"]["capital"])
    cash, quantity, fees = capital, Decimal(0), Decimal(0)
    peak, drawdown = capital, Decimal(0)
    curve = [
        dict(time=pd.to_datetime(start, unit="us", utc=True).isoformat(), equity=float(capital))
    ]
    with localcontext() as context:
        context.prec = 100
        for fill in fills:
            q, price, fee = (Decimal(fill[k]) for k in ("quantity", "price", "fee"))
            sign = 1 if fill["side"] == "BUY" else -1
            cash -= sign * q * price + fee
            quantity += sign * q
            fees += fee
        for charge in charges:
            amount = Decimal(charge["amount"])
            cash -= amount
            fees += amount
        for point in points:
            equity = Decimal(point["equity"])
            peak = max(peak, equity)
            drawdown = max(drawdown, (peak - equity) / peak)
            curve.append(
                dict(
                    time=pd.to_datetime(point["timestamp"], unit="us", utc=True).isoformat(),
                    equity=float(equity),
                )
            )
        equity = Decimal(points[-1]["equity"]) if points else capital
        pnl = equity - capital
    visible_counts = seen.groupby("session_date").size()
    total_counts = bars.groupby("session_date").size().to_dict()
    finished = {day for day, count in visible_counts.items() if count == total_counts[day]}
    filled_by_order: dict[str, Decimal] = {}
    for fill in fills:
        key = fill["order_id"]
        filled_by_order[key] = filled_by_order.get(key, Decimal(0)) + Decimal(fill["quantity"])
    orders = [
        dict(
            Created=pd.to_datetime(o["request"]["timestamp"], unit="us", utc=True).isoformat(),
            Side=o["request"]["side"],
            Quantity=o["request"]["quantity"],
            Filled=str(filled_by_order.get(o["order_id"], Decimal(0))),
            Order=o["order_id"],
        )
        for o in account["orders"]
        if int(o["request"]["timestamp"]) < clock
    ]
    return dict(
        candles=candles,
        equity=curve,
        fills=fills,
        orders=orders,
        markers=[
            dict(
                time=pd.to_datetime(f["timestamp"], unit="us", utc=True).isoformat(),
                price=float(f["price"]),
                side=f["side"],
            )
            for f in fills
        ],
        charges=charges,
        cash=cash,
        position=quantity,
        fees=fees,
        pnl=pnl,
        current_equity=equity,
        drawdown=drawdown,
        clock=clock,
        daily=[d for d in account["daily"] if d["day"] in finished],
        complete=cursor == len(bars),
    )
