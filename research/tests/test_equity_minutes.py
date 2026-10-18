"""Minute source, causality, real-clock execution and policy regression fixtures."""

import json
from datetime import date
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from helios.alpha.evaluator import AlphaSeries
from helios.alpha.output import bound_alpha
from helios.backtest.equity import replay_session
from helios.equities.calendar import normal_sessions
from helios.equities.config import EquityResearchPolicy
from helios.equities.features import minute_samples
from helios.equities.public_data import history_url, month_ranges, parse_candles


def minute_fixture(day="2026-01-09"):
    stamps = pd.date_range(day + " 09:15", periods=375, freq="min", tz="Asia/Kolkata")
    return pd.DataFrame(
        dict(
            symbol="EXAMPLE",
            timestamp=stamps.tz_convert("UTC"),
            open_time=stamps.as_unit("us").astype("int64"),
            session_date=day,
            available_at=(stamps + pd.Timedelta(minutes=1)).tz_convert("UTC"),
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
            adjusted_close=100.0,
            volume=10000.0,
            full_bar=True,
        )
    )


def test_public_request_ranges_do_not_overlap_and_refuse_invalid_isin():
    assert month_ranges(date(2025, 1, 20), date(2025, 3, 2)) == [
        (date(2025, 1, 20), date(2025, 1, 31)),
        (date(2025, 2, 1), date(2025, 2, 28)),
        (date(2025, 3, 1), date(2025, 3, 2)),
    ]
    assert "NSE_EQ%7CINE002A01018/minutes/1/" in history_url(
        "INE002A01018", date(2025, 1, 1), date(2025, 1, 2)
    )
    with pytest.raises(ValueError):
        history_url("../x", date(2025, 1, 1), date(2025, 1, 2))


def test_public_source_preserves_prices_and_excludes_bad_observations():
    rows = [
        ["2025-01-02T09:15:00+05:30", 100, 101, 99, 100.5, 10, 0],
        ["2025-01-02T09:16:00+05:30", 100, 99, 98, 100, 20, 0],
    ]
    body = json.dumps(dict(status="success", data=dict(candles=rows))).encode()
    frame, excluded = parse_candles(body, "EXAMPLE", date(2025, 1, 2), date(2025, 1, 2))
    assert frame.close.tolist() == [100.5] and excluded == {"invalid_ohlcv": 1}
    assert frame.available_at.iloc[0] - frame.timestamp.iloc[0] == pd.Timedelta(minutes=1)
    with pytest.raises(ValueError, match="outside"):
        parse_candles(body, "EXAMPLE", date(2025, 1, 3), date(2025, 1, 3))


@pytest.mark.leakage
def test_minute_features_and_labels_respect_gaps_and_future_mutations():
    bars = minute_fixture()
    before = minute_samples(bars, include_unlabelled=True)
    mutated = bars.copy()
    mutated.loc[mutated.index >= 100, ["open", "high", "low", "close", "volume"]] = np.nan
    after = minute_samples(mutated, include_unlabelled=True)
    columns = ["return_1", "return_2", "return_3", "volatility_3", "feature_available"]
    pd.testing.assert_frame_equal(before.loc[:99, columns], after.loc[:99, columns])
    broken = minute_samples(bars.drop(index=100))
    assert not (broken.label_open_time - broken.timestamp > pd.Timedelta(minutes=1)).any()
    assert (broken.label_session == broken.session_date).all()


def test_minute_execution_uses_next_observed_open_and_real_final_exit():
    bars = minute_fixture()
    alpha = bound_alpha(
        AlphaSeries(
            "EXAMPLE",
            bars.open_time,
            pd.Series(1.0, index=bars.index),
            pd.Series(True, index=bars.index),
        )
    )
    policy = EquityResearchPolicy(version="nse_minute_research_v1", interval="1m")
    result = replay_session(
        bars, alpha, policy, snapshot_id="a" * 64, alpha_id="nse_fixture", code_commit="b" * 40
    )
    assert len(result.trace.snapshots) == 375 and result.n_fills == 2
    assert result.fills[0]["timestamp"] == int(bars.open_time.iloc[1])
    assert result.fills[-1]["timestamp"] == int(bars.open_time.iloc[-1])
    assert result.trace.positions[-1].quantity == 0
    assert result.trace.snapshots[-1].equity == Decimal("99800")
    assert result.net_return == -0.002


def test_official_calendar_requires_supported_year_and_excludes_holiday(tmp_path):
    raw = tmp_path / "calendar.json"
    raw.write_text(json.dumps(dict(CM=[dict(tradingDate="15-Jan-2026")])))
    assert normal_sessions(raw, date(2026, 1, 14), date(2026, 1, 18)) == (
        "2026-01-14",
        "2026-01-16",
    )
    with pytest.raises(ValueError, match="outside"):
        normal_sessions(raw, date(2025, 1, 1), date(2025, 1, 3))


def test_frequency_version_must_match():
    with pytest.raises(ValueError, match="frequency"):
        EquityResearchPolicy(interval="1m")
