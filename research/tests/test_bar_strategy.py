from decimal import Decimal as D

import pytest
from pydantic import ValidationError
from test_common_types import lineage

from helios.common.types import AlphaStatus, AlphaValue
from helios.sim.strategy import TargetConfig, target_notional


def alpha(value=0.5, **changes):
    return AlphaValue(
        **(
            dict(
                symbol="BTCUSDT",
                timestamp=10,
                status=AlphaStatus.OK,
                value=value,
                lineage=lineage(),
            )
            | changes
        )
    )


@pytest.mark.parametrize("value,expected", [(1, "2000"), (-1, "-2000"), (0.5, "1000"), (0, "0")])
def test_signed_target_respects_capital_and_coin_weight(value, expected):
    result = target_notional(alpha(value), TargetConfig(capital=D(10000), max_weight=D("0.2")))
    assert result.notional == D(expected) and result.lineage == lineage()
    assert result.symbol == "BTCUSDT" and result.timestamp == 10


@pytest.mark.parametrize("status", [AlphaStatus.UNAVAILABLE, AlphaStatus.STALE])
def test_unavailable_signal_is_not_a_zero_position_target(status):
    assert (
        target_notional(alpha(None, status=status), TargetConfig(capital=D(1), max_weight=D(1)))
        is None
    )


@pytest.mark.parametrize(
    "changes", [dict(capital=0), dict(capital="NaN"), dict(max_weight=0), dict(max_weight="1.01")]
)
def test_invalid_allocation_refused(changes):
    with pytest.raises(ValidationError):
        TargetConfig(**(dict(capital=D(100), max_weight=D("0.2")) | changes))
