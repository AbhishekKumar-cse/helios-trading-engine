"""Runtime boundary invariants and immutable nested command round trips."""

from decimal import Decimal as D

import pytest
from pydantic import TypeAdapter, ValidationError

from helios.common.project_config import HorizonFamily
from helios.common.types import (
    AlphaStatus,
    AlphaValue,
    AuthorisedOrder,
    Bar,
    BookView,
    CancelOrder,
    DecisionLineage,
    ExecutionReport,
    FeatureValue,
    FeatureVector,
    Fill,
    Mode,
    NewOrder,
    Order,
    OrderAction,
    OrderState,
    OrderType,
    PnLSnapshot,
    Position,
    ReasonCode,
    Reject,
    RiskDecision,
    Side,
    TimeInForce,
    VenueInfo,
)


def lineage():
    return DecisionLineage(
        alpha_id="example",
        alpha_version=1,
        feature_set_version="v1",
        horizon_family=HorizonFamily.HOURLY,
        code_commit="a" * 40,
        config_hash="b" * 64,
        snapshot_id="snapshot",
        seed=0,
    )


def request(**changes):
    return NewOrder(
        **(
            dict(
                client_order_id="client-1",
                strategy_id="strategy",
                symbol="BTCUSDT",
                side=Side.BUY,
                order_type=OrderType.LIMIT,
                quantity=D("0.3"),
                price=D("100"),
                time_in_force=TimeInForce.GTC,
                timestamp=10,
                lineage=lineage(),
                mode=Mode.BACKTEST,
            )
            | changes
        )
    )


def test_exact_quantity_conservation_and_immutable_nested_serialization() -> None:
    order = Order(
        order_id="order-1",
        request=request(),
        state=OrderState.PARTIALLY_FILLED,
        filled_quantity=D("0.1"),
        remaining_quantity=D("0.2"),
        timestamp=11,
    )
    assert Order.model_validate_json(order.model_dump_json()) == order
    with pytest.raises(ValidationError):
        order.request.quantity = D("99")
    for changes in (
        {"remaining_quantity": D("0.1")},
        {"state": OrderState.FILLED},
        {"state": OrderState.ACCEPTED},
        {"timestamp": 9},
    ):
        with pytest.raises(ValidationError):
            Order.model_validate(order.model_dump() | changes)


@pytest.mark.parametrize("bad", [D("NaN"), D("Infinity"), D("-1"), D("0")])
def test_prices_and_quantities_cannot_be_nonfinite_or_nonpositive(bad) -> None:
    with pytest.raises(ValidationError):
        request(quantity=bad)
    with pytest.raises(ValidationError):
        request(price=bad)


def test_action_union_and_market_limit_requirements() -> None:
    adapter = TypeAdapter(OrderAction)
    new = request()
    cancel = CancelOrder(
        request_id="cancel-1",
        order_id="order-1",
        symbol="BTCUSDT",
        timestamp=11,
        lineage=lineage(),
        mode=Mode.PAPER,
    )
    for action in (new, cancel):
        assert adapter.validate_json(adapter.dump_json(action)) == action
    for changes in ({"price": None}, {"order_type": OrderType.MARKET}, {"mode": "LIVE"}):
        with pytest.raises(ValidationError):
            request(**changes)
    assert (
        request(order_type=OrderType.MARKET, price=None, time_in_force=TimeInForce.IOC).price
        is None
    )


def test_database_precision_quantities_are_conserved_without_context_rounding() -> None:
    order = Order(
        order_id="precise",
        request=request(quantity=D("99999999999999999999.000000000000000001")),
        state=OrderState.PARTIALLY_FILLED,
        filled_quantity=D("99999999999999999999"),
        remaining_quantity=D("0.000000000000000001"),
        timestamp=11,
    )
    assert order.remaining_quantity == D("0.000000000000000001")
    with pytest.raises(ValidationError):
        request(quantity=D("0.0000000000000000001"))


def test_alpha_and_feature_availability_are_not_zero_imputation() -> None:
    common = dict(symbol="BTCUSDT", timestamp=10, lineage=lineage())
    assert AlphaValue(**common, status=AlphaStatus.UNAVAILABLE, value=None).value is None
    assert AlphaValue(**common, status=AlphaStatus.OK, value=0).value == 0
    for status, value in (
        (AlphaStatus.OK, None),
        (AlphaStatus.STALE, 0),
        (AlphaStatus.OK, 2),
        (AlphaStatus.OK, True),
    ):
        with pytest.raises(ValidationError):
            AlphaValue(**common, status=status, value=value)
    feature = FeatureValue(name="volatility", available=False, value=None)
    with pytest.raises(ValidationError):
        FeatureValue(name="volatility", available=False, value=0)
    with pytest.raises(ValidationError):
        FeatureVector(
            symbol="BTCUSDT",
            timestamp=10,
            snapshot_id="snapshot",
            feature_set_version="v1",
            features=(feature, feature),
        )


def test_risk_decision_fails_closed_without_action_and_limits_hash() -> None:
    reject = RiskDecision(accepted=False, reason=ReasonCode.MISSING_LIMITS, timestamp=11)
    assert reject.authorised is None
    authorised = AuthorisedOrder(action=request(), limits_hash="c" * 64)
    assert RiskDecision(
        accepted=True, reason=ReasonCode.ACCEPTED, timestamp=11, authorised=authorised
    ).accepted
    for changes in (
        {"accepted": True},
        {"authorised": authorised},
        {"reason": ReasonCode.ACCEPTED},
    ):
        with pytest.raises(ValidationError):
            RiskDecision.model_validate(reject.model_dump() | changes)
    with pytest.raises(ValidationError):
        Reject(request_id="x", timestamp=1, reason=ReasonCode.ACCEPTED)


def test_bar_times_ohlc_and_book_spread() -> None:
    fields = dict(
        symbol="BTCUSDT",
        source="fixture",
        sequence=1,
        open_time=0,
        ingest_time=3_600_000_000,
        interval="1h",
        open=D(100),
        high=D(110),
        low=D(90),
        close=D(105),
        volume=D(0),
        snapshot_id="snapshot",
    )
    assert Bar(**fields).close_time == 3_600_000_000
    for changes in ({"high": D(99)}, {"ingest_time": 1}, {"open_time": True}, {"sequence": -1}):
        with pytest.raises(ValidationError):
            Bar(**(fields | changes))
    with pytest.raises(ValidationError):
        BookView(
            symbol="BTCUSDT", timestamp=1, sequence=1, best_bid=D(101), best_ask=D(100), stale=False
        )


def test_fill_report_position_and_pnl_validation() -> None:
    fill = Fill(
        fill_id="fill-1",
        order_id="order-1",
        symbol="BTCUSDT",
        side=Side.BUY,
        quantity=D("0.1"),
        price=D(100),
        fee=D("0.01"),
        fee_asset="USDT",
        timestamp=11,
        venue_id="paper",
        liquidity="TAKER",
        mode=Mode.PAPER,
    )
    report = ExecutionReport(
        order_id="order-1",
        client_order_id="client-1",
        sequence=1,
        timestamp=11,
        state=OrderState.PARTIALLY_FILLED,
        filled_quantity=D("0.1"),
        remaining_quantity=D("0.2"),
        fill=fill,
    )
    assert ExecutionReport.model_validate_json(report.model_dump_json()) == report
    with pytest.raises(ValidationError):
        ExecutionReport.model_validate(report.model_dump() | {"order_id": "other"})
    assert (
        Position(
            symbol="BTCUSDT", quantity=D("-0.1"), average_entry_price=D(100), timestamp=11
        ).quantity
        < 0
    )
    with pytest.raises(ValidationError):
        Position(symbol="BTCUSDT", quantity=D(1), average_entry_price=None, timestamp=11)
    pnl = PnLSnapshot(
        timestamp=11,
        quote_asset="USDT",
        cash=D(100),
        equity=D(101),
        realized_pnl=D(0),
        unrealized_pnl=D(1),
        fees=D(0),
        mode=Mode.BACKTEST,
        config_hash="b" * 64,
    )
    assert PnLSnapshot.model_validate_json(pnl.model_dump_json()) == pnl
    for value in (False, 1):
        with pytest.raises(ValidationError):
            VenueInfo(venue_id="paper", is_simulated=value, supports_amend=False)
