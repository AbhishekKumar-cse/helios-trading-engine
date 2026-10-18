"""Synthetic NSE PAPER adapter checks; no market observations are invented."""

import json
from decimal import Decimal

import pandas as pd
import pytest
from test_loss_risk import Store

from helios.alpha.definition import AlphaDefinition
from helios.common.types import Mode, OrderState
from helios.equities.live import EquityClosedCandle, yahoo_public_quote
from helios.equities.paper_config import equity_paper_config
from helios.paper.runtime import PaperRuntime, PaperSafetyStop


def candle(offset):
    opened = (
        int(pd.Timestamp("2026-01-09 09:15", tz="Asia/Kolkata").value // 1000) + offset * 60_000_000
    )
    return EquityClosedCandle(
        symbol="EXAMPLE",
        open_time=opened,
        recorded_close_time=opened + 60_000_000 - 1,
        event_time=opened + 60_000_000,
        received_time=opened + 60_000_000 + 10_000,
        open=Decimal(100),
        high=Decimal(101),
        low=Decimal(99),
        close=Decimal(100) + Decimal(offset) / 10,
        volume=Decimal(10000),
    )


def runtime():
    config = equity_paper_config(
        "nse_paper_fixture", "a" * 64, "nse_paper_fixture_alpha", "EXAMPLE"
    )
    definition = AlphaDefinition(
        alpha_id=config.alpha_id,
        version=1,
        name="Synthetic equity PAPER test",
        provenance="QUANT",
        feature_set_version="nse_session_features_v1",
        horizon_family="H-MINUTE",
        horizon_periods=1,
        expression="clip(sign(return_1),0,1)",
        author="test",
    )
    return PaperRuntime(config, definition, "b" * 40, Store())


def quote(stamp, symbol="EXAMPLE"):
    return json.dumps(
        dict(
            chart=dict(
                result=[
                    dict(
                        meta=dict(
                            symbol=symbol + ".NS",
                            currency="INR",
                            exchangeTimezoneName="Asia/Kolkata",
                            regularMarketTime=stamp // 1_000_000,
                            regularMarketPrice=100.4,
                        )
                    )
                ]
            )
        )
    )


def test_equity_paper_uses_shared_components_and_fresh_later_inr_quote():
    live = runtime()
    for offset in range(4):
        live.closed(candle(offset))
    assert live.oms.snapshot()[-1].state is OrderState.ACCEPTED
    assert not any(report.fill for report in live.reports)
    stamp = candle(3).event_time + 2_000_000
    live.message(quote(stamp), stamp + 10_000)
    fill = next(report.fill for report in live.reports if report.fill is not None)
    assert fill.fee_asset == "INR" and fill.mode is Mode.PAPER
    assert fill.quantity == fill.quantity.to_integral_value()
    assert fill.timestamp > live.oms.snapshot()[0].request.timestamp
    assert live.snapshots[-1].quote_asset == "INR"


@pytest.mark.leakage
def test_equity_paper_refuses_quote_from_before_the_order_and_cancels():
    live = runtime()
    for offset in range(4):
        live.closed(candle(offset))
    stamp = candle(3).event_time
    with pytest.raises(PaperSafetyStop, match="predates"):
        live.message(quote(stamp), stamp + 20_000)
    assert live.store.is_tripped(live.config.run_id)
    assert live.oms.snapshot()[0].state is OrderState.CANCELLED
    assert not any(report.fill for report in live.reports)


def test_equity_quote_identity_must_match_currency_and_symbol():
    with pytest.raises(ValueError, match="identity"):
        yahoo_public_quote(quote(candle(3).event_time, "OTHER"), "EXAMPLE")
