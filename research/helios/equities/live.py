"""Typed public equity observations; scheduled bar close is not a quote timestamp."""

import json
from decimal import Decimal
from typing import Literal, Self

from pydantic import Field, model_validator

from helios.common.market_clock import nse_bar_complete
from helios.common.types import NonNegative, Price, Record, Timestamp


class EquityClosedCandle(Record):
    source: Literal["upstox_public_minute"] = "upstox_public_minute"
    symbol: str = Field(pattern=r"^[A-Z0-9&-]+$")
    open_time: Timestamp
    recorded_close_time: Timestamp
    event_time: Timestamp
    received_time: Timestamp
    open: Price
    high: Price
    low: Price
    close: Price
    volume: NonNegative

    @model_validator(mode="after")
    def closed_normal_minute(self) -> Self:
        end = self.recorded_close_time + 1
        if (
            not nse_bar_complete(self.open_time, end, "1m")
            or self.event_time != end
            or self.received_time < end
        ):
            raise ValueError("completed observed normal NSE minute required")
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("invalid equity OHLC")
        return self


def yahoo_public_quote(raw: str | bytes, symbol: str) -> tuple[int, int, Decimal]:
    """Return the provider's last-trade time, not an invented current quote time."""
    payload = json.loads(raw)
    meta = payload["chart"]["result"][0]["meta"]
    if (
        meta["symbol"] != symbol + ".NS"
        or meta["currency"] != "INR"
        or meta["exchangeTimezoneName"] != "Asia/Kolkata"
    ):
        raise ValueError("public equity quote identity mismatch")
    event, value = meta["regularMarketTime"], meta["regularMarketPrice"]
    if type(event) is not int or event <= 0 or isinstance(value, bool):
        raise ValueError("public quote needs an actual last-trade timestamp and price")
    price = Decimal(str(value))
    if not price.is_finite() or price <= 0:
        raise ValueError("invalid public last-trade price")
    stamp = event * 1_000_000
    return stamp // 60_000_000 * 60_000_000, stamp, price
