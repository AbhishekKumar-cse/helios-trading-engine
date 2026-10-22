"""Delayed public observations remain causal, bounded and explicitly simulated."""

from decimal import Decimal
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from streamlit.testing.v1 import AppTest
from test_equity_paper import candle, quote, runtime
from test_loss_risk import Store

from helios.common.types import OrderState
from helios.equities.paper_config import EquityPaperConfig, equity_paper_config
from helios.paper.runtime import PaperRuntime, PaperSafetyStop


def delayed_runtime():
    strict = runtime()
    config = equity_paper_config(
        strict.config.run_id,
        strict.config.stream_id,
        strict.config.alpha_id,
        strict.config.symbol,
        timing="delayed_public",
    )
    return PaperRuntime(config, strict.definition, "b" * 40, Store())


def delayed_candle(offset, delay=43_000_000):
    original = candle(offset)
    return original.model_copy(update={"received_time": original.event_time + delay})


def warm(live):
    for offset in range(4):
        live.closed(delayed_candle(offset))


def test_delayed_policy_is_separate_and_strict_limits_cannot_be_widened():
    strict = runtime().config
    delayed = delayed_runtime().config
    assert strict.max_event_skew_us == 5_000_000
    assert strict.max_intent_age_us == 10_000_000
    assert delayed.max_event_skew_us == 120_000_000
    assert delayed.max_intent_age_us == 180_000_000
    assert delayed.purpose == "delayed_public_data_simulation"
    assert delayed.fill_model == "delayed_public_price_proxy_v1"
    for changes in (
        {"max_event_skew_us": 120_000_000},
        {"max_intent_age_us": 180_000_000},
        {"version": delayed.version},
    ):
        with pytest.raises(ValidationError):
            EquityPaperConfig.model_validate(strict.model_dump() | changes)
    with pytest.raises(ValidationError):
        EquityPaperConfig.model_validate(delayed.model_dump() | {"max_event_skew_us": 121_000_000})


def test_delayed_candle_keeps_exchange_and_receipt_clocks_and_creates_no_fill():
    live = delayed_runtime()
    warm(live)
    assert live.bars[-1].event_time == candle(3).event_time
    assert live.signals[-1].timestamp == candle(3).event_time + 43_000_000
    assert live.oms.snapshot()[0].request.timestamp == live.signals[-1].timestamp
    assert not any(r.fill for r in live.reports)
    with pytest.raises(PaperSafetyStop, match="stale_feed"):
        runtime().closed(delayed_candle(0))


@pytest.mark.leakage
def test_delayed_quote_before_intent_waits_and_only_genuine_later_trade_fills():
    live = delayed_runtime()
    warm(live)
    intent = live.oms.snapshot()[0].request.timestamp
    earlier = candle(3).event_time + 2_000_000
    live.message(quote(earlier), intent + 1_000_000)
    assert not any(r.fill for r in live.reports)
    assert live.oms.snapshot()[0].state is OrderState.ACCEPTED
    later = intent + 2_000_000
    live.message(quote(later), later + 43_000_000)
    fill = next(r.fill for r in live.reports if r.fill is not None)
    assert fill.timestamp == later + 43_000_000
    assert later > intent
    assert fill.fee_asset == "INR"


def test_delayed_quote_can_cross_minute_boundary_but_not_use_expired_features():
    live = delayed_runtime()
    warm(live)
    later = candle(3).event_time + 62_000_000
    live.message(quote(later), later + 1_000_000)
    assert any(r.fill for r in live.reports)
    with pytest.raises(PaperSafetyStop, match="candle_age"):
        live.message(quote(later + 60_000_000), later + 61_000_000)


@pytest.mark.parametrize("delay", [120_000_001, -5_000_001])
def test_delayed_allowance_does_not_accept_unbounded_age_or_future_prices(delay):
    live = delayed_runtime()
    event = candle(0).event_time
    with pytest.raises(PaperSafetyStop, match="stale_feed"):
        live.observe(event + delay, event, Decimal(100))


def test_delayed_startup_and_missing_candles_remain_bounded():
    live = delayed_runtime()
    start = candle(0).event_time
    live.check_health(start + 180_000_000, started_at=start)
    with pytest.raises(PaperSafetyStop, match="feed_silence"):
        live.check_health(start + 180_000_001, started_at=start)
    live = delayed_runtime()
    warm(live)
    with pytest.raises(PaperSafetyStop, match="candle_age"):
        live.check_health(candle(3).event_time + 120_000_001, started_at=start)
    assert live.oms.snapshot()[0].state is OrderState.CANCELLED


def test_pending_intent_expires_even_when_new_candles_keep_arriving():
    live = delayed_runtime()
    warm(live)
    pending = live.oms.snapshot()[0].request.timestamp
    for offset in range(4, 7):
        live.closed(delayed_candle(offset))
    assert live.oms.snapshot()[0].request.timestamp == pending
    with pytest.raises(PaperSafetyStop, match="pending_intent"):
        live.check_health(pending + 180_000_001, started_at=candle(0).event_time)
    assert all(o.state is OrderState.CANCELLED for o in live.oms.snapshot())
    assert not any(r.fill for r in live.reports)


def test_delayed_mode_keeps_kill_and_missing_minute_guards():
    live = delayed_runtime()
    warm(live)
    live.halt("synthetic_operator")
    with pytest.raises(PaperSafetyStop, match="operator_kill"):
        live.check_health(live.clock + 1, started_at=candle(0).event_time)
    assert live.oms.snapshot()[0].state is OrderState.CANCELLED
    live = delayed_runtime()
    live.closed(delayed_candle(0))
    with pytest.raises(PaperSafetyStop, match="bar_gap"):
        live.closed(delayed_candle(2))


def test_dashboard_labels_delayed_simulation():
    config = delayed_runtime().config
    view = dict(
        runs=[dict(paper_run_id=config.run_id)],
        run=dict(
            paper_run_id=config.run_id,
            status="finished",
            config_json=config.model_dump(mode="json"),
        ),
        halted=True,
        pnl=None,
        positions=[],
        orders=[],
    )
    with patch("helios.dashboard.paper_page.read_paper", return_value=view):
        app = AppTest.from_string(
            "from helios.dashboard.paper_page import render_paper\nrender_paper()",
            default_timeout=30,
        ).run()
    assert not app.exception
    assert any("Delayed-data simulation" in item.value for item in app.info)
