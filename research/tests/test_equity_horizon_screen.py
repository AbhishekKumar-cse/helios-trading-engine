"""Known-prefix, label-boundary and independent-account cost controls."""

from datetime import date
from decimal import Decimal

import pytest
from test_equity_rebuild import reviewed_frame

from helios.equities.horizon_screen import EXITS, cost_screen, forward_return, opening_features


@pytest.mark.leakage
def test_opening_features_ignore_all_later_prices_and_volumes():
    frame = reviewed_frame("2025-09-01").astype(
        {c: float for c in ("open", "high", "low", "close")}
    )
    before = opening_features(frame)
    frame.loc[30:, ["open", "high", "low", "close", "volume"]] = 999
    assert before == opening_features(frame)
    assert before["move_30"] == 0 and before["location_30"] == 0.5


@pytest.mark.leakage
def test_forward_label_has_exact_next_open_horizon_and_rejects_gaps():
    frame = reviewed_frame("2025-09-01")
    frame.loc[EXITS["m60"], "open"] = 102
    assert forward_return(frame, EXITS["m60"]) == pytest.approx(0.02)
    frame.loc[EXITS["m60"] + 1 :, "open"] = 900
    assert forward_return(frame, EXITS["m60"]) == pytest.approx(0.02)
    broken = frame.copy()
    broken.loc[5, "open_time"] += 1
    with pytest.raises(ValueError, match="missing minute"):
        forward_return(broken, EXITS["m60"])
    broken = frame.copy()
    broken.loc[90:, "session_date"] = "2025-09-02"
    with pytest.raises(ValueError, match="session"):
        forward_return(broken, EXITS["m60"])


def test_cost_screen_sizes_at_known_close_and_preserves_quantity_under_stress():
    args = (date(2025, 9, 1), "EXAMPLE", Decimal(100), Decimal(101), Decimal(103))
    base = cost_screen(*args, active=True, multiplier=1)
    stress = cost_screen(*args, active=True, multiplier=2)
    assert base["quantity"] == stress["quantity"] == "500"
    assert Decimal(base["gross"]) == 1000
    assert Decimal(stress["net"]) < Decimal(base["net"])
    assert Decimal(base["net"]) == Decimal(base["gross"]) - Decimal(base["slippage"]) - Decimal(
        base["fees"]
    )


def test_no_entry_is_an_observed_cash_day_and_unavailable_features_are_not_zero():
    args = (date(2025, 9, 1), "EXAMPLE", Decimal(100), Decimal(101), Decimal(103))
    assert set(cost_screen(*args, active=False, multiplier=1).values()) == {"0"}
    frame = reviewed_frame("2025-09-01")
    frame.loc[0, "volume"] = 0
    with pytest.raises(ValueError, match="unavailable"):
        opening_features(frame)
