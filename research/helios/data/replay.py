"""Historical Parquet bar events, merged by close availability and symbol (120)."""

from __future__ import annotations

import heapq
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from helios.common.types import Bar, Mode
from helios.data.bars import DEFAULT_OUT_DIR
from helios.data.binance import sha256_file
from helios.data.klines import interval_us
from helios.data.loader import TimeLike, load_bars, to_micros
from helios.data.snapshots import compute_snapshot_id, load_manifest
from helios.sim.positions import _times


class ReplayError(ValueError):
    """Unknown or inconsistent source observations are not repaired silently."""


@dataclass(frozen=True)
class ReplayIssue:
    symbol: str
    open_time: int
    reason: Literal["DATA_GAP", "PARTIAL_OR_OFF_GRID"]
    missing_intervals: int = 0


class HistoricalBarSource:
    mode = Mode.REPLAY

    def __init__(
        self,
        symbols: tuple[str, ...],
        start: TimeLike,
        end: TimeLike,
        *,
        snapshot_id: str,
        interval: Literal["1h", "1m"] = "1h",
        bars_dir: Path = DEFAULT_OUT_DIR,
        loader: Callable[[], pd.DataFrame] | None = None,
        strict_gaps: bool = False,
    ) -> None:
        first, last = to_micros(start), to_micros(end, end=True)
        if interval not in ("1h", "1m") or not isinstance(strict_gaps, bool):
            raise ReplayError("replay requires hourly/minute interval and boolean gap policy")
        if loader is None and not re.fullmatch(r"[0-9a-f]{64}", snapshot_id):
            raise ReplayError("replay requires a canonical snapshot SHA-256 identifier")
        if (
            not symbols
            or len(set(symbols)) != len(symbols)
            or any(not re.fullmatch(r"[A-Z0-9]+", symbol) for symbol in symbols)
            or first is None
            or last is None
            or first > last
        ):
            raise ReplayError("replay requires unique symbols and explicit ordered bounds")
        self.symbols = tuple(sorted(symbols))
        self.first, self.last = first, last
        self.snapshot_id, self.interval, self.bars_dir = snapshot_id, interval, bars_dir
        self.loader, self.strict_gaps = loader, strict_gaps
        self._issues: list[ReplayIssue] = []

    @property
    def issues(self) -> tuple[ReplayIssue, ...]:
        return tuple(self._issues)

    def events(self) -> Iterator[Bar]:
        self._issues = []
        period = interval_us(self.interval)
        if self.loader is None:
            snapshot = load_manifest(self.snapshot_id)
            if (
                snapshot.snapshot_id != self.snapshot_id
                or compute_snapshot_id(snapshot.files) != self.snapshot_id
            ):
                raise ReplayError("snapshot identity mismatch")
            if snapshot.interval != self.interval or not set(self.symbols).issubset(
                snapshot.symbols
            ):
                raise ReplayError("snapshot universe/interval mismatch")
            first_year = pd.Timestamp(self.first, unit="us").year
            last_year = pd.Timestamp(self.last, unit="us").year
            for file in snapshot.files:
                if any(f"symbol={symbol}/" in file.path for symbol in self.symbols) and any(
                    f"year={year}/" in file.path for year in range(first_year, last_year + 1)
                ):
                    path = (self.bars_dir / file.path).resolve()
                    if (
                        not path.is_relative_to(self.bars_dir.resolve())
                        or sha256_file(path) != file.sha256
                    ):
                        raise ReplayError("snapshot file checksum mismatch")
            frame = load_bars(
                self.symbols, self.interval, self.first, self.last, out_dir=self.bars_dir
            )
        else:
            frame = self.loader().copy(deep=True)
        columns = {"symbol", "open_time", "close_time", "open", "high", "low", "close", "volume"}
        if not frame.columns.is_unique or not columns.issubset(frame.columns):
            raise ReplayError("replay requires canonical unique bar columns")
        if not set(frame.symbol.unique()).issubset(self.symbols):
            raise ReplayError("unexpected instrument in replay input")
        streams: list[Iterator[Any]] = []
        for symbol in self.symbols:
            group = frame.loc[frame.symbol == symbol]
            _times(group.open_time)
            _times(group.close_time)
            if ((group.open_time < self.first) | (group.open_time > self.last)).any():
                raise ReplayError("loader returned rows outside requested bounds")
            streams.append(iter(group.itertuples(index=False)))
        heap: list[tuple[int, str, int, Any]] = []
        for i, stream in enumerate(streams):
            row = next(stream, None)
            if row is not None:
                resolution = 1000 if int(row.close_time) % 1000 == 0 else 1
                heapq.heappush(heap, (int(row.close_time) + resolution, self.symbols[i], i, row))
        previous: dict[str, int] = {}
        sequences = {symbol: 0 for symbol in self.symbols}
        while heap:
            closing, symbol, i, row = heapq.heappop(heap)
            bar = Bar(
                symbol=symbol,
                source="binance_parquet_REPLAY",
                sequence=sequences[symbol],
                open_time=int(row.open_time),
                recorded_close_time=int(row.close_time),
                ingest_time=closing,
                close_time_resolution_us=1000 if int(row.close_time) % 1000 == 0 else 1,
                interval=self.interval,
                open=Decimal(str(row.open)),
                high=Decimal(str(row.high)),
                low=Decimal(str(row.low)),
                close=Decimal(str(row.close)),
                volume=Decimal(str(row.volume)),
                snapshot_id=self.snapshot_id,
            )
            issues = []
            if not bar.is_complete_interval:
                issues.append(ReplayIssue(symbol, bar.open_time, "PARTIAL_OR_OFF_GRID"))
            if symbol in previous and bar.open_time - previous[symbol] > period:
                issues.append(
                    ReplayIssue(
                        symbol,
                        bar.open_time,
                        "DATA_GAP",
                        max(0, (bar.open_time - previous[symbol]) // period - 1),
                    )
                )
            self._issues.extend(issues)
            if issues and self.strict_gaps:
                raise ReplayError(f"{symbol} has replay availability issues at {bar.open_time}")
            previous[symbol] = bar.open_time
            sequences[symbol] += 1
            yield bar
            next_row = next(streams[i], None)
            if next_row is not None:
                resolution = 1000 if int(next_row.close_time) % 1000 == 0 else 1
                heapq.heappush(heap, (int(next_row.close_time) + resolution, symbol, i, next_row))
