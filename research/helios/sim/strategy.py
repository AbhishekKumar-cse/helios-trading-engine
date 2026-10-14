"""Fixed capital allocation and bar strategy intents; no venue submission (122)."""

from decimal import ROUND_DOWN, Decimal, localcontext
from typing import Annotated

from pydantic import Field

from helios.common.types import (
    AlphaStatus,
    AlphaValue,
    DecisionLineage,
    Identifier,
    Money,
    Price,
    Record,
    Timestamp,
)

PRECISION = Decimal("0.000000000000000001")


class TargetConfig(Record):
    capital: Price
    max_weight: Annotated[
        Decimal, Field(gt=0, le=1, allow_inf_nan=False, max_digits=38, decimal_places=18)
    ]


class TargetNotional(Record):
    symbol: Identifier
    timestamp: Timestamp
    notional: Money
    lineage: DecisionLineage


def target_notional(alpha: AlphaValue, config: TargetConfig) -> TargetNotional | None:
    """Signed per-coin target = capital * max_weight * bounded alpha.

    Unavailable/stale signals produce no target, not a silently substituted zero.
    Currency rounding is toward zero at the shared numeric(38,18) boundary.
    Portfolio/exposure authorization is independently enforced by later risk checks.
    """
    if alpha.status is not AlphaStatus.OK or alpha.value is None:
        return None
    with localcontext() as context:
        context.prec = 80
        target = (config.capital * config.max_weight * Decimal(str(alpha.value))).quantize(
            PRECISION, rounding=ROUND_DOWN
        )
    return TargetNotional(
        symbol=alpha.symbol, timestamp=alpha.timestamp, notional=target, lineage=alpha.lineage
    )
