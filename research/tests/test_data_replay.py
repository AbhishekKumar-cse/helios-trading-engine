"""Canonical source order, real close precision, gap visibility and snapshot checks."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest

from helios.common.interfaces import MarketDataSource
from helios.common.types import Mode
from helios.data.replay import HistoricalBarSource, ReplayError
from helios.data.snapshots import SnapshotFile, compute_snapshot_id

HOUR = 3_600_000_000


def bars():
    return pd.DataFrame(
        [
            dict(
                symbol=symbol,
                open_time=t,
                close_time=t + HOUR - 1,
                open=100.0,
                high=110.0,
                low=90.0,
                close=105.0,
                volume=1.0,
            )
            for symbol in ("ETHUSDT", "BTCUSDT")
            for t in (0, HOUR, 3 * HOUR)
        ]
    )


def source(frame=None, **changes):
    return HistoricalBarSource(
        ("ETHUSDT", "BTCUSDT"),
        0,
        4 * HOUR,
        snapshot_id="fixture",
        loader=lambda: bars() if frame is None else frame,
        **changes,
    )


def test_merges_independent_streams_by_close_time_symbol_and_surfaces_gaps() -> None:
    replay = source()
    typed: MarketDataSource = replay
    events = list(typed.events())
    assert [(e.close_time, e.symbol) for e in events] == sorted(
        (e.close_time, e.symbol) for e in events
    )
    assert len(events) == 6 and replay.mode is Mode.REPLAY
    assert [e.sequence for e in events if e.symbol == "BTCUSDT"] == [0, 1, 2]
    assert all(e.ingest_time == e.close_time and e.is_complete_interval for e in events)
    assert len(replay.issues) == 2 and all(i.missing_intervals == 1 for i in replay.issues)
    assert len(list(replay.events())) == 6 and len(replay.issues) == 2


def test_issues_are_not_exposed_before_their_event_and_strict_mode_refuses() -> None:
    replay = source()
    iterator = replay.events()
    for _ in range(4):
        next(iterator)
        assert not replay.issues
    next(iterator)
    assert len(replay.issues) == 1
    with pytest.raises(ReplayError, match="availability"):
        list(source(strict_gaps=True).events())


def test_ms_precision_and_partial_bar_keep_real_recorded_close() -> None:
    frame = bars().iloc[:2].copy()
    frame.loc[frame.index[0], "close_time"] = HOUR - 1000
    frame.loc[frame.index[1], "close_time"] = HOUR + HOUR // 2 - 1000
    events = list(source(frame).events())
    assert events[0].recorded_close_time == HOUR - 1000 and events[0].close_time == HOUR
    assert events[0].close_time_resolution_us == 1000 and events[0].is_complete_interval
    assert events[1].close_time == HOUR + HOUR // 2 and not events[1].is_complete_interval
    frame.loc[frame.index[1], "close_time"] = 2 * HOUR + 475000
    replay = source(frame)
    late = list(replay.events())[1]
    assert late.close_time == 2 * HOUR + 476000 and not late.is_complete_interval
    assert replay.issues[0].reason == "PARTIAL_OR_OFF_GRID"


def test_does_not_silently_sort_duplicate_or_backwards_per_symbol_input() -> None:
    frame = bars()
    with pytest.raises(ValueError, match="chronological"):
        list(source(frame.iloc[[1, 0, 2, 3, 4, 5]]).events())
    with pytest.raises(ValueError, match="unique"):
        list(source(pd.concat([frame, frame.iloc[:1]])).events())
    frame.loc[0, "symbol"] = "UNKNOWN"
    with pytest.raises(ReplayError, match="unexpected"):
        list(source(frame).events())


def test_snapshot_hash_change_is_refused_before_loading(tmp_path: Path) -> None:
    relative = "source=binance/interval=1h/symbol=BTCUSDT/year=1970/bars.parquet"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(b"changed")
    file = SnapshotFile(relative, "a" * 64, 7)
    snapshot_id = compute_snapshot_id([file])
    metadata = SimpleNamespace(
        snapshot_id=snapshot_id, files=[file], interval="1h", symbols=["BTCUSDT"]
    )
    with (
        patch("helios.data.replay.load_manifest", return_value=metadata),
        patch("helios.data.replay.load_bars") as loader,
    ):
        with pytest.raises(ReplayError, match="checksum"):
            list(
                HistoricalBarSource(
                    ("BTCUSDT",), 0, HOUR, snapshot_id=snapshot_id, bars_dir=tmp_path
                ).events()
            )
    loader.assert_not_called()


def test_requires_explicit_bounds_and_does_not_invent_empty_instruments() -> None:
    with pytest.raises(ReplayError, match="bounds"):
        HistoricalBarSource(("BTCUSDT",), None, None, snapshot_id="fixture", loader=bars)
    with pytest.raises(ReplayError, match="unique"):
        HistoricalBarSource(("BTCUSDT", "BTCUSDT"), 0, HOUR, snapshot_id="fixture", loader=bars)
    empty = bars().iloc[:0].copy()
    replay = source(empty)
    assert not list(replay.events()) and not replay.issues
