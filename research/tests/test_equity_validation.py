"""Synthetic fixtures for public-reference safety and independent charge examples."""

import io
import json
from dataclasses import replace
from datetime import date
from decimal import Decimal as D
from zipfile import ZipFile

import pandas as pd
import pytest

from helios.data.equities import sha256, write_json
from helios.equities.charges import ChargeTrade, estimate_intraday_charges
from helios.equities.validation import (
    bhavcopy,
    corporate_events,
    known_preinclusion_rows,
    price_scale_check,
    verified_references,
)


def trade(side="BUY", quantity="500", price="100", order="buy", day=date(2026, 2, 27)):
    return ChargeTrade(day, "EXAMPLE", order, side, D(quantity), D(price))


def test_published_stt_example_uses_combined_vwap_and_client_day_rounding():
    estimate = estimate_intraday_charges([trade(), trade("SELL", price="105", order="sell")])
    # Independent published example: 500 * INR102.50 * .025% =12.8125 ->13.
    assert estimate.stt == D(13)
    assert estimate.brokerage == D("30.75")
    assert estimate.stamp == D("1.5")
    assert estimate.turnover == D(102500)


def test_partial_fills_share_one_brokerage_cap_and_outcome_is_order_independent():
    fills = [
        trade(quantity="500", price="200"),
        trade(quantity="500", price="200"),
        trade("SELL", quantity="1000", price="200", order="sell"),
    ]
    estimate = estimate_intraday_charges(fills)
    assert estimate.orders == 2 and estimate.brokerage == D(40)
    assert estimate == estimate_intraday_charges(list(reversed(fills)))


def test_dated_exchange_ipft_reclassification_does_not_double_charge():
    old = [trade(), trade("SELL", order="sell")]
    new = [replace(t, day=date(2026, 3, 2)) for t in old]
    before, after = map(estimate_intraday_charges, (old, new))
    assert before.exchange == D("2.97") and before.ipft == D("0.1")
    assert after.exchange == D("3.0699") and after.ipft == D("0.0001")
    assert before.total == after.total
    assert before.gst == (before.brokerage + D("3.17")) * D(".18")


def test_stt_rounds_once_per_client_day_after_aggregating_securities():
    # Two securities each incur .49, so a client-day total .98 rounds to1, not0.
    rows = [trade(quantity="49", price="40"), trade("SELL", "49", "40", "sell")]
    assert estimate_intraday_charges(rows).stt == 0
    assert (
        estimate_intraday_charges(
            rows + [replace(t, symbol="SECOND", order_id=t.order_id + "2") for t in rows]
        ).stt
        == 1
    )


@pytest.mark.parametrize("qty,price", [("1.5", "10"), ("0", "10"), ("1", "NaN"), ("1", "-1")])
def test_charge_trade_rejects_unexecutable_or_nonfinite_inputs(qty, price):
    with pytest.raises(ValueError):
        trade(quantity=qty, price=price)


def test_costs_refuse_test_dates_nonflat_positions_and_conflicting_order_identity():
    with pytest.raises(ValueError):
        trade(day=date(2026, 7, 9))
    with pytest.raises(ValueError, match="non-flat"):
        estimate_intraday_charges([trade()])
    with pytest.raises(ValueError, match="cannot change"):
        estimate_intraday_charges([trade(), trade("SELL")])


def test_corporate_action_dates_are_not_claimed_as_known_announcement_times():
    payload = [
        dict(
            symbol="EXAMPLE",
            series="EQ",
            exDate="26-Aug-2025",
            isin="INE000A01010",
            subject="Bonus 1:1",
            caBroadcastDate=None,
        )
    ]
    events = corporate_events(
        json.dumps(payload).encode(), "EXAMPLE", date(2025, 1, 1), date(2026, 6, 30)
    )
    assert events[0]["kind"] == "capital_or_other"
    assert events[0]["point_in_time_availability_verified"] is False
    with pytest.raises(ValueError):
        corporate_events(json.dumps(payload).encode(), "WRONG", date(2025, 1, 1), date(2026, 6, 30))
    with pytest.raises(ValueError):
        corporate_events(b'{"error":"denied"}', "EXAMPLE", date(2025, 1, 1), date(2026, 6, 30))


def test_membership_boundary_is_effective_date_not_announcement_date():
    rows = pd.Series(["2025-03-27", "2025-03-28", "2025-03-31"], index=[3, 4, 5])
    assert known_preinclusion_rows(rows, included_on=date(2025, 3, 28)).tolist() == [
        True,
        False,
        False,
    ]
    with pytest.raises(ValueError):
        known_preinclusion_rows(pd.Series(["not-a-date"]), included_on=date(2025, 3, 28))


def test_official_daily_file_verifies_embedded_trade_date_and_eq_identity():
    columns = "TradDt,ISIN,TckrSymb,SctySrs,OpnPric,HghPric,LwPric,ClsPric,LastPric,TtlTradgVol\n"
    row = "2025-06-16,INE000A01010,EXAMPLE,EQ,100,102,98,101,101,500\n"
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("official.csv", columns + row)
    parsed = bhavcopy(buffer.getvalue(), date(2025, 6, 16))
    assert parsed.ISIN.tolist() == ["INE000A01010"]
    with pytest.raises(ValueError, match="trade date"):
        bhavcopy(buffer.getvalue(), date(2025, 6, 17))


def test_different_closing_benchmarks_are_not_automatically_called_scale_errors():
    minute = pd.DataFrame(dict(high=[102], low=[98], close=[100], volume=[10]))
    official = pd.Series(dict(HghPric=102, LwPric=98, ClsPric=101, LastPric=100, TtlTradgVol=15))
    assert price_scale_check(minute, official)["status"] == "NO_LARGE_SCALE_SHIFT_DETECTED"
    minute[["high", "low", "close"]] *= 0.5
    assert price_scale_check(minute, official)["status"] == "PRICE_SCALE_REVIEW"
    official.HghPric = float("nan")
    with pytest.raises(ValueError):
        price_scale_check(minute, official)


@pytest.mark.parametrize("tamper", ["payload", "manifest_status", "traversal"])
def test_reference_collection_refuses_changed_bytes_metadata_or_escaping_paths(tmp_path, tamper):
    root = tmp_path / "refs"
    root.mkdir()
    (root / "body.raw").write_bytes(b"public reference fixture")
    write_json(root / "protocol.json", {"purpose": "synthetic validation fixture"})
    row = dict(key="fixture", path="body.raw", status=200, sha256=sha256(root / "body.raw"))
    (root / "requests.jsonl").write_text(json.dumps(row) + "\n")
    manifest = dict(
        version="nse_public_reference_audit_v1",
        complete=True,
        sources=[dict(row)],
        protocol_sha256=sha256(root / "protocol.json"),
        requests_sha256=sha256(root / "requests.jsonl"),
    )
    write_json(root / "manifest.json", manifest)
    assert verified_references(root)["fixture"]["status"] == 200
    if tamper == "payload":
        (root / "body.raw").write_bytes(b"changed")
    elif tamper == "manifest_status":
        manifest["sources"][0]["status"] = 403
        (root / "manifest.json").write_text(json.dumps(manifest))
    else:
        (tmp_path / "escaped.raw").write_bytes(b"public reference fixture")
        row["path"] = "../escaped.raw"
        (root / "requests.jsonl").write_text(json.dumps(row) + "\n")
        manifest["sources"] = [row]
        manifest["requests_sha256"] = sha256(root / "requests.jsonl")
        (root / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        verified_references(root)
