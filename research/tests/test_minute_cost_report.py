import pytest

from helios.sim.minute_cost_report import render, summarize


def evidence():
    return dict(
        protocol=dict(definition=dict(horizon_family="H-MINUTE")),
        status="REJECTED",
        series=[
            dict(gross_return=None, cost=None, net_return=None),
            dict(gross_return=0.002, cost=0.0012, net_return=0.0008),
        ],
        costs=dict(
            points=[
                dict(
                    multiplier=m,
                    cost_bps=12 * m,
                    total_cost=0.0012 * m,
                    metrics=dict(
                        metrics=dict(annual_sharpe=1 - m, total_return=0.002 - 0.0012 * m)
                    ),
                )
                for m in (0.5, 1, 2, 3, 4)
            ]
        ),
    )


def test_saved_curve_and_paired_reconciliation(tmp_path):
    row = summarize(evidence())
    assert row["gross_bps_per_turnover"] == pytest.approx(20)
    assert row["n_paired"] == 1 and len(row["curve"]) == 5
    render([row | dict(alpha_id="minute_fixture")], tmp_path)
    assert (tmp_path / "minute_cost_reality.svg").stat().st_size > 1000
    assert (tmp_path / "minute_cost_reality.png").stat().st_size > 1000
    changed = evidence()
    changed["series"][1]["net_return"] = 0.002
    with pytest.raises(ValueError, match="reconcile"):
        summarize(changed)


def test_invalid_does_not_invent_zero_performance():
    row = summarize(
        dict(protocol=dict(definition=dict(horizon_family="H-MINUTE")), status="INVALID")
    )
    assert row["gross"] is row["net"] is None and row["curve"] == []
