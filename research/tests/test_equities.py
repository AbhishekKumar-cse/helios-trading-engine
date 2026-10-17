"""Equity calendar, provenance and causal training-boundary regressions."""

import csv
import io
import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from helios.common.config import config_hash, load_config
from helios.data.equities import (
    EquityPilotConfig,
    constituents,
    parse_chart,
    sha256,
    write_json,
)
from helios.ml.equity_pilot import FEATURES, features_and_labels, load_inputs, split_samples


def config() -> EquityPilotConfig:
    return load_config("configs/equities/nifty50_pilot.yaml", EquityPilotConfig)


def daily(symbol: str = "EXAMPLE", start: str = "2022-01-03", periods: int = 800) -> pd.DataFrame:
    times = pd.date_range(start, periods=periods, freq="B", tz="Asia/Kolkata") + pd.Timedelta(
        hours=9, minutes=15
    )
    close = 100 * np.exp(np.sin(np.arange(periods) / 7) * 0.02 + np.arange(periods) * 0.001)
    opening = close * (1 + 0.005 * np.cos(np.arange(periods)))
    return pd.DataFrame(
        dict(
            symbol=symbol,
            timestamp=times.tz_convert("UTC"),
            session_date=times.strftime("%Y-%m-%d"),
            available_at=(times.normalize() + pd.Timedelta(days=1)).tz_convert("UTC"),
            open=opening,
            high=np.maximum(opening, close) * 1.01,
            low=np.minimum(opening, close) * 0.99,
            close=close,
            volume=1000 + np.arange(periods),
            adjusted_close=close,
            full_bar=True,
        )
    )


def hourly() -> pd.DataFrame:
    frame = daily(periods=15)
    parts = []
    for slot in range(7):
        part = frame.copy()
        part["timestamp"] += pd.Timedelta(hours=slot)
        part["available_at"] = part["timestamp"] + pd.Timedelta(minutes=60 if slot < 6 else 15)
        part["full_bar"] = slot < 6
        parts.append(part)
    return pd.concat(parts).sort_values("timestamp").reset_index(drop=True)


def chart(times: list[int]) -> bytes:
    return json.dumps(
        dict(
            chart=dict(
                result=[
                    dict(
                        meta=dict(
                            symbol="EXAMPLE.NS",
                            currency="INR",
                            exchangeName="NSI",
                            exchangeTimezoneName="Asia/Kolkata",
                        ),
                        timestamp=times,
                        indicators=dict(
                            quote=[
                                dict(
                                    open=[100.0] * len(times),
                                    high=[102.0] * len(times),
                                    low=[99.0] * len(times),
                                    close=[101.0] * len(times),
                                    volume=[100.0] * len(times),
                                )
                            ],
                            adjclose=[dict(adjclose=[50.5] * len(times))],
                        ),
                    )
                ],
                error=None,
            )
        )
    ).encode()


def roster() -> bytes:
    output = io.StringIO()
    writer = csv.DictWriter(
        output, fieldnames=["Company Name", "Industry", "Symbol", "Series", "ISIN Code"]
    )
    writer.writeheader()
    for i in range(50):
        writer.writerow(
            {
                "Company Name": f"Example {i}",
                "Industry": "Fixture",
                "Symbol": f"EQ{i}",
                "Series": "EQ",
                "ISIN Code": f"INE{i:09d}",
            }
        )
    return output.getvalue().encode()


def test_official_universe_requires_50_distinct_equity_identities() -> None:
    assert len(constituents(roster())) == 50
    with pytest.raises(ValueError, match="exactly 50"):
        constituents(b"Company Name,Industry,Symbol,Series,ISIN Code\n")
    with pytest.raises(ValueError, match="duplicate"):
        constituents(roster().replace(b"EQ49", b"EQ48"))


def test_intraday_partial_hour_and_timezone() -> None:
    times = pd.date_range("2026-10-12 09:15", periods=7, freq="h", tz="Asia/Kolkata")
    frame, quality = parse_chart(
        chart([int(t.timestamp()) for t in times]),
        "EXAMPLE",
        "60m",
        date(2026, 10, 10),
        date(2026, 10, 17),
    )
    assert frame["full_bar"].tolist() == [True] * 6 + [False]
    assert quality["partial_bars"] == 1
    assert frame.iloc[-1]["available_at"] == pd.Timestamp("2026-10-12 10:00Z")
    assert frame.iloc[0]["timestamp"] == pd.Timestamp("2026-10-12 03:45Z")


def test_missing_quotes_and_duplicate_timestamps_are_explicit() -> None:
    stamp = int(pd.Timestamp("2026-10-12 09:15", tz="Asia/Kolkata").timestamp())
    with pytest.raises(ValueError, match="duplicate"):
        parse_chart(chart([stamp, stamp]), "EXAMPLE", "1d", date(2026, 10, 10), date(2026, 10, 17))
    payload = json.loads(chart([stamp, stamp + 86400]))
    payload["chart"]["result"][0]["indicators"]["quote"][0]["close"][0] = None
    frame, quality = parse_chart(
        json.dumps(payload).encode(), "EXAMPLE", "1d", date(2026, 10, 10), date(2026, 10, 17)
    )
    assert len(frame) == 1
    assert quality["rejected_rows"] == {"missing_or_nonfinite": 1}


@pytest.mark.leakage
def test_future_prices_cannot_change_earlier_features_or_labels() -> None:
    frame = daily(periods=100)
    before = features_and_labels(frame, "1d")
    cutoff = frame.iloc[70]["timestamp"]
    frame.loc[frame.index >= 70, ["open", "high", "low", "close", "adjusted_close"]] *= 5
    after = features_and_labels(frame, "1d")
    left = before.loc[before["label_open_time"] < cutoff, ["timestamp", *FEATURES, "target"]]
    right = after.loc[after["label_open_time"] < cutoff, ["timestamp", *FEATURES, "target"]]
    pd.testing.assert_frame_equal(left, right)


def test_global_adjustment_rescaling_cancels_and_labels_use_next_open_close() -> None:
    frame = daily(periods=60)
    original = features_and_labels(frame, "1d")
    frame["adjusted_close"] *= 0.5
    rescaled = features_and_labels(frame, "1d")
    np.testing.assert_allclose(original[list(FEATURES)], rescaled[list(FEATURES)])
    following = frame.set_index("timestamp").loc[original["label_open_time"]]
    np.testing.assert_allclose(original["target"], following["close"] / following["open"] - 1)


@pytest.mark.leakage
def test_hourly_labels_exclude_partial_hours_overnight_and_missing_hours() -> None:
    frame = hourly()
    # Remove a full hour after warm-up; its preceding sample must lose its target.
    removed = frame.iloc[65]["timestamp"]
    frame = frame.loc[frame["timestamp"] != removed]
    samples = features_and_labels(frame, "60m")
    assert not samples.empty
    assert (samples["session_date"] == samples["label_session"]).all()
    assert ((samples["label_open_time"] - samples["timestamp"]) == pd.Timedelta(hours=1)).all()
    assert samples["full_bar"].all()
    assert removed not in set(samples["label_open_time"])
    assert (samples["available_at"] <= samples["label_open_time"]).all()


@pytest.mark.leakage
def test_splits_purge_cross_boundary_labels_and_never_use_test() -> None:
    frame = daily(periods=1000)
    train, valid, _ = split_samples([frame], config(), "1d")
    assert train["label_session"].max() <= "2022-12-31"
    assert valid["session_date"].min() >= "2023-01-09"
    assert valid["label_session"].max() <= "2024-12-31"
    assert train["label_end_time"].max() < valid["timestamp"].min()
    frame.loc[frame["session_date"] >= "2025-01-01", "close"] = 1e10
    train_again, valid_again, _ = split_samples([frame], config(), "1d")
    pd.testing.assert_frame_equal(train, train_again)
    pd.testing.assert_frame_equal(valid, valid_again)


def test_hourly_opening_zero_volume_is_excluded_without_inventing_bars() -> None:
    frame = hourly()
    opening = frame["timestamp"].dt.tz_convert("Asia/Kolkata").dt.hour == 9
    frame.loc[opening, "volume"] = 0
    samples = features_and_labels(frame, "60m")
    assert len(samples) >= 10
    assert (samples["volume"] > 0).all()
    assert not samples["timestamp"].isin(frame.loc[opening, "timestamp"]).any()
    assert not samples["label_open_time"].isin(frame.loc[opening, "timestamp"]).any()
    assert set(samples["timestamp"]).issubset(set(frame["timestamp"]))


def test_snapshot_integrity_filter_and_missing_constituents(tmp_path: Path) -> None:
    (tmp_path / "constituents.csv").write_bytes(roster())
    write_json(tmp_path / "protocol.json", config().model_dump(mode="json"))
    records = []
    for i in range(50):
        symbol = f"EQ{i}"
        path, raw = tmp_path / f"{symbol}.parquet", tmp_path / f"{symbol}.json"
        daily(symbol, "2024-12-20", 30).to_parquet(path, index=False)
        raw.write_text("{}")
        records.append(
            dict(
                symbol=symbol,
                interval="1d",
                path=path.name,
                sha256=sha256(path),
                raw_path=raw.name,
                raw_sha256=sha256(raw),
            )
        )
    manifest = dict(
        config_hash=config_hash(config()),
        protocol_sha256=sha256(tmp_path / "protocol.json"),
        universe_sha256=sha256(tmp_path / "constituents.csv"),
        files=records,
    )
    write_json(tmp_path / "manifest.json", manifest)
    frames, _, _ = load_inputs(tmp_path, config(), "1d")
    assert len(frames) == 50
    assert all(frame["session_date"].max() <= "2024-12-31" for frame in frames)
    (tmp_path / "EQ49.json").write_text('{"tampered": true}')
    with pytest.raises(ValueError, match="fingerprint"):
        load_inputs(tmp_path, config(), "1d")
    manifest["files"] = records[:-1]
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="all 50"):
        load_inputs(tmp_path, config(), "1d")


def test_runs_are_append_only_and_protocol_rejects_small_embargo(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    write_json(path, {"original": True})
    with pytest.raises(FileExistsError):
        write_json(path, {"original": False})
    values = config().model_dump()
    values["daily_valid_start"] = date(2023, 1, 2)
    with pytest.raises(ValueError, match="embargo"):
        EquityPilotConfig.model_validate(values)
