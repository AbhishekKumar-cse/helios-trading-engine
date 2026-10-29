from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from helios.dashboard.equity_page import read_development_bars
from helios.data.equities import sha256


@pytest.mark.leakage
@pytest.mark.parametrize("interval, cutoff", [("1d", "2024-12-31"), ("60m", "2026-06-30")])
def test_equity_chart_cannot_display_reserved_test_prices(tmp_path, interval, cutoff):
    from test_equities import config, daily

    path = tmp_path / "bars.parquet"
    frame = daily(start=cutoff, periods=10)
    frame.to_parquet(path, index=False)
    record = dict(path=path.name, sha256=sha256(path), interval=interval)
    displayed = read_development_bars(tmp_path, record, config())
    assert not displayed.empty
    assert displayed["session_date"].max() <= cutoff
    frame["close"] += 1
    frame.to_parquet(path, index=False)
    with pytest.raises(ValueError, match="fingerprint"):
        read_development_bars(tmp_path, record, config())


def test_equity_page_is_read_only_and_handles_absent_downloads(tmp_path):
    with (
        patch("helios.dashboard.equity_page.PROJECT_ROOT", tmp_path),
        patch("helios.dashboard.equity_page.retained_snapshots", return_value=[]),
        patch("helios.dashboard.registry.read_registry", side_effect=AssertionError("DB access")),
    ):
        app = AppTest.from_file(
            str(Path("dashboards/streamlit/app.py").resolve()), default_timeout=30
        )
        app.query_params["page"] = "equities"
        app.run()
        assert not app.exception
        assert app.query_params["page"] == "equities"
        assert any(b.label == "NSE backtest" for b in app.sidebar.button)
        assert app.title[0].value == "Nifty 50 research lab"
        assert any("No completed equity download" in item.value for item in app.info)


def test_equity_page_renders_downloaded_prices_without_database(tmp_path):
    from test_equities import config, daily, roster

    from helios.data.equities import write_json

    snapshot = tmp_path / "data/equities/nifty50/fixture"
    snapshot.mkdir(parents=True)
    (snapshot / "constituents.csv").write_bytes(roster())
    write_json(snapshot / "protocol.json", config().model_dump(mode="json"))
    path = snapshot / "EQ0_1d.parquet"
    daily("EQ0", periods=100).to_parquet(path, index=False)
    write_json(
        snapshot / "manifest.json",
        dict(
            universe_sha256=sha256(snapshot / "constituents.csv"),
            created_at="fixture",
            members=[{"Symbol": "EQ0", "Company Name": "Example fixture"}],
            failures=[],
            files=[
                dict(
                    symbol="EQ0",
                    interval="1d",
                    path=path.name,
                    sha256=sha256(path),
                    retained_bars=100,
                    first_session="2022-01-03",
                    last_session="2022-05-20",
                    partial_bars=0,
                    rejected_rows={},
                )
            ],
        ),
    )
    with (
        patch("helios.dashboard.equity_page.PROJECT_ROOT", tmp_path),
        patch("helios.dashboard.equity_research.PROJECT_ROOT", tmp_path),
        patch("helios.dashboard.registry.read_registry", side_effect=AssertionError("DB access")),
    ):
        app = AppTest.from_file(
            str(Path("dashboards/streamlit/app.py").resolve()), default_timeout=30
        )
        app.query_params["page"] = "equities"
        app.run()
        assert not app.exception
        assert app.metric[0].value == "100"
        assert len(app.get("vega_lite_chart")) == 1
        assert len(app.dataframe[0].value) == 1
        assert all(button.key.startswith("nav_") for button in app.button)
