"""NSE playback cannot reveal next-opening fills or future settlement charges."""

from copy import deepcopy
from decimal import Decimal

import pandas as pd
import pytest

from helios.dashboard.nse_replay import replay_view


def fixture():
    bars = pd.DataFrame(
        dict(
            open_time=[0, 60, 120, 180],
            session_date="fixture",
            open=[100, 100, 100, 110],
            high=[101, 101, 111, 111],
            low=[99, 99, 99, 109],
            close=[100, 100, 110, 110],
        )
    )
    account = dict(
        equity=[
            dict(timestamp=t, equity=str(v))
            for t, v in zip([60, 120, 180, 240], [1000, 999, 1009, 1005], strict=True)
        ],
        fills=[
            dict(timestamp=60, quantity="1", price="100", fee="1", side="BUY", order_id="a"),
            dict(timestamp=180, quantity="1", price="110", fee="1", side="SELL", order_id="b"),
        ],
        fee_adjustments=[dict(timestamp=240, amount="3")],
        daily=[dict(day="fixture", net_pnl="5")],
        orders=[dict(order_id="a", request=dict(timestamp=60, side="BUY", quantity="1"))],
    )
    return dict(options=dict(capital="1000")), dict(scenarios={"1": account}), bars


def test_clock_boundary_and_end_settlement_are_replayed_in_original_order():
    protocol, result, bars = fixture()
    zero = replay_view(protocol, result, bars, 0)
    assert not zero["candles"] and not zero["fills"] and zero["cash"] == 1000
    first = replay_view(protocol, result, bars, 1)
    assert not first["fills"] and first["pnl"] == 0
    second = replay_view(protocol, result, bars, 2)
    assert len(second["fills"]) == 1 and second["cash"] == 899 and second["position"] == 1
    third = replay_view(protocol, result, bars, 3)
    assert len(third["fills"]) == 1 and not third["charges"]
    last = replay_view(protocol, result, bars, 4)
    assert len(last["fills"]) == 2 and last["fees"] == 5 and last["cash"] == 1005
    assert last["pnl"] == 5 and last["position"] == 0 and len(last["daily"]) == 1


@pytest.mark.parametrize("cursor", [0, 1, 2, 3])
def test_future_price_fill_fee_and_equity_mutation_cannot_change_replay_prefix(cursor):
    p, r, b = fixture()
    before = replay_view(p, r, b, cursor)
    changed = deepcopy(r)
    changed["scenarios"]["1"]["equity"][3]["equity"] = "99999"
    changed["scenarios"]["1"]["fills"][1]["price"] = "99999"
    changed["scenarios"]["1"]["fee_adjustments"][0]["amount"] = "99999"
    changed_bars = b.copy()
    changed_bars.loc[3, ["open", "high", "low", "close"]] = 99999
    assert replay_view(p, changed, changed_bars, cursor) == before


def test_every_reached_snapshot_reconciles_cash_inventory_and_mark():
    p, r, b = fixture()
    for cursor in range(1, 5):
        view = replay_view(p, r, b, cursor)
        marked = view["cash"] + view["position"] * Decimal(str(b.close.iloc[cursor - 1]))
        assert view["current_equity"] == marked
    with pytest.raises(ValueError):
        replay_view(p, r, b, 5)
    with pytest.raises(ValueError):
        replay_view(p, r, b.iloc[:2], 1)
