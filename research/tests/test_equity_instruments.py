"""Current public metadata is not a live quote or a guessed tick rule."""

from decimal import Decimal

import pytest

from helios.equities.instruments import public_instrument


def fixture(tick=".05", lot="1", exchange="NSE"):
    return (
        "instrument_token,exchange_token,tradingsymbol,name,last_price,tick_size,lot_size,instrument_type,segment,exchange\n"
        f"123,456,EXAMPLE,Fixture,0,{tick},{lot},EQ,NSE,{exchange}\n"
    ).encode()


def test_exact_nse_symbol_and_price_independent_tick_metadata():
    value = public_instrument(fixture(), "EXAMPLE")
    assert value.tick_size == Decimal(".05") and value.lot_size == 1
    with pytest.raises(ValueError, match="exact symbol"):
        public_instrument(fixture(), "OTHER")
    with pytest.raises(ValueError, match="whole-share"):
        public_instrument(fixture(lot="10"), "EXAMPLE")
    with pytest.raises(ValueError, match="positive tick"):
        public_instrument(fixture(tick="0"), "EXAMPLE")
