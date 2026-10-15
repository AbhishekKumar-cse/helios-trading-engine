"""Historical decision clock and next-opening action scheduling (121).

This schedules intents; a caller must apply risk/OMS before simulated execution.
It does not create fills or treat submission as execution.
"""

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from helios.common.interfaces import MarketDataSource
from helios.common.types import Bar, Mode, NewOrder, OrderAction


@dataclass(frozen=True)
class BarOpen:
    symbol: str
    timestamp: int
    price: Decimal
    snapshot_id: str


@dataclass(frozen=True)
class ScheduledAction:
    action: OrderAction
    decision_open_time: int
    available_at: int


class BarEventLoop:
    def run(
        self,
        source: MarketDataSource,
        decide: Callable[[Bar], list[OrderAction]],
        act: Callable[[OrderAction, BarOpen], None],
        *,
        opened: Callable[[BarOpen], None] | None = None,
        closed: Callable[[Bar], None] | None = None,
    ) -> tuple[ScheduledAction, ...]:
        """Materialize a historical timeline; expose only opening prices at opens.

        At equal clocks, completed bars precede openings, so a decision at t's
        close can act at t+1's open. A late close cannot act retroactively. Missing
        or irregular intervals fail before any callback; no synthetic events.
        Returns tail intents that never reached another eligible opening.
        """
        bars = list(source.events())
        previous: dict[str, Bar] = {}
        snapshot = bars[0].snapshot_id if bars else None
        keys = [(bar.close_time, bar.symbol) for bar in bars]
        if keys != sorted(keys):
            raise ValueError("historical source must be ordered by close time and symbol")
        timeline: list[tuple[int, int, str, Bar]] = []
        for bar in bars:
            old = previous.get(bar.symbol)
            if (
                bar.snapshot_id != snapshot
                or not bar.is_complete_interval
                or (
                    old is not None
                    and (bar.interval != old.interval or bar.open_time != old.close_time)
                )
            ):
                raise ValueError("event loop requires complete contiguous snapshot bars")
            previous[bar.symbol] = bar
            timeline.extend(
                ((bar.open_time, 1, bar.symbol, bar), (bar.ingest_time, 0, bar.symbol, bar))
            )
        pending: list[ScheduledAction] = []
        seen: set[str] = set()
        for clock, phase, symbol, bar in sorted(timeline, key=lambda item: item[:3]):
            if phase == 0:
                if closed is not None:
                    closed(bar)
                actions = decide(bar)
                staged = []
                for action in actions:
                    identifier = (
                        action.client_order_id
                        if isinstance(action, NewOrder)
                        else action.request_id
                    )
                    if (
                        action.symbol != symbol
                        or action.timestamp != clock
                        or action.mode not in (Mode.BACKTEST, Mode.REPLAY)
                        or action.lineage.snapshot_id != bar.snapshot_id
                        or identifier in seen
                    ):
                        raise ValueError(
                            "intent must match clock, symbol, snapshot and simulated mode"
                        )
                    seen.add(identifier)
                    staged.append(ScheduledAction(action, bar.open_time, clock))
                pending.extend(staged)
            else:
                opening = BarOpen(symbol, clock, bar.open, bar.snapshot_id)
                ready = [
                    p
                    for p in pending
                    if p.action.symbol == symbol
                    and p.available_at <= clock
                    and p.decision_open_time < bar.open_time
                ]
                pending = [p for p in pending if p not in ready]
                for intent in ready:
                    act(intent.action, opening)
                if opened is not None:
                    opened(opening)
        return tuple(pending)
