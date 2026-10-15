from decimal import Decimal as D

import pytest
from test_common_types import request
from test_event_loop import H, bars
from test_paper_venue import opening

from helios.common.project_config import load_fees
from helios.common.types import CancelOrder, Mode, OrderState, Reject, Side, TimeInForce
from helios.sim.paper import BarPaperVenue


def venue_and_reports():
    fees = load_fees().model_copy(update={"maker_fee_bps": 3, "taker_fee_bps": 10})
    venue = BarPaperVenue(Mode.BACKTEST, fees)
    reports = []
    venue.subscribe_reports(reports.append)
    return venue, reports


@pytest.mark.parametrize(
    "side,limit,touch,through",
    [
        (Side.BUY, 95, {"low": D(95)}, {"low": D(94)}),
        (Side.SELL, 108, {"high": D(108)}, {"high": D(109)}),
    ],
)
def test_strict_passive_trade_through_next_bar_only(side, limit, touch, through):
    venue, reports = venue_and_reports()
    action = request(timestamp=H, side=side, price=D(limit))
    venue.submit(action)
    venue.on_open(opening(H))
    assert len(reports) == 1
    bar = bars()[1].model_copy(update={"open": D(100)} | touch)
    venue.on_bar(bar)
    assert len(reports) == 1  # a touch is insufficient
    venue.on_open(opening(2 * H))
    venue.on_bar(bars()[2].model_copy(update={"open": D(100)} | through))
    fill = reports[-1].fill
    assert fill.price == D(limit) and fill.liquidity == "MAKER"
    assert fill.timestamp == 3 * H and fill.fee == D(limit) * D("0.3") * D(".0003")
    assert not venue.snapshot_open_orders()


@pytest.mark.parametrize(
    "side,limit,expected", [(Side.BUY, "100.01", "100.01"), (Side.SELL, "99.99", "99.99")]
)
def test_marketable_limit_is_taker_with_slippage_capped_at_limit(side, limit, expected):
    venue, reports = venue_and_reports()
    venue.submit(request(side=side, price=D(limit)))
    venue.on_open(opening())
    fill = reports[-1].fill
    assert fill.price == D(expected) and fill.liquidity == "TAKER"
    assert fill.fee == D(expected) * D(".3") * D(".001")


@pytest.mark.parametrize("tif", [TimeInForce.IOC, TimeInForce.FOK])
def test_non_crossing_immediate_limit_expires_at_open(tif):
    venue, reports = venue_and_reports()
    venue.submit(request(price=D(95), time_in_force=tif))
    venue.on_open(opening())
    assert reports[-1].state is OrderState.EXPIRED and reports[-1].fill is None
    assert reports[-1].remaining_quantity == D(".3")


def test_bar_clock_and_cancel_cannot_retroactively_erase_intrabar_execution():
    venue, reports = venue_and_reports()
    action = request(timestamp=H, price=D(95))
    ack = venue.submit(action)
    venue.on_open(opening(H))
    with pytest.raises(ValueError, match="previous"):
        venue.on_open(opening(2 * H))
    cancel = CancelOrder(
        request_id="cancel",
        order_id=ack.order_id,
        symbol=action.symbol,
        timestamp=H + 1,
        lineage=action.lineage,
        mode=action.mode,
    )
    assert isinstance(venue.cancel(cancel), Reject)
    venue.on_bar(bars()[1].model_copy(update={"open": D(100), "low": D(94)}))
    assert reports[-1].state is OrderState.FILLED
    with pytest.raises(ValueError, match="advance"):
        venue.on_bar(bars()[1].model_copy(update={"open": D(100)}))


def test_zero_volume_and_late_submission_cannot_use_prior_bar_range():
    venue, reports = venue_and_reports()
    venue.on_open(opening(H))
    venue.submit(request(timestamp=H + 1, price=D(95)))
    venue.on_bar(bars()[1].model_copy(update={"open": D(100)}))
    assert not any(r.fill for r in reports)
    venue.on_open(opening(2 * H))
    venue.on_bar(bars()[2].model_copy(update={"open": D(100), "volume": D(0)}))
    assert not any(r.fill for r in reports)
