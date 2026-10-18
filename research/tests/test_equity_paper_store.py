"""Rolled-back NSE PAPER persistence from explicitly synthetic test observations."""

from datetime import UTC, datetime

from sqlalchemy import text
from test_equity_paper import candle, quote, runtime
from test_paper_store import paper_engine  # noqa: F401

from helios.alpha.definition import register_alpha_definition
from helios.common.config import config_hash
from helios.common.lineage import RunContext
from helios.data.equities import sha256
from helios.paper.runtime import PaperRuntime
from helios.paper.store import PaperStore
from helios.sim.loss_risk import PostgresTripStore


def test_nse_paper_checkpoints_preserve_inr_whole_shares(
    paper_engine,  # noqa: F811 - shared pytest fixture
    connection,
    tmp_path,
):
    fixture = runtime()
    config, definition = fixture.config, fixture.definition
    connection.execute(
        text("""INSERT INTO instruments
        (symbol,venue,base_asset,quote_asset,tick_size,lot_size,first_available_date)
        VALUES ('EXAMPLE','nse_cash','EXAMPLE','INR',.05,1,'2025-01-01')
        ON CONFLICT(symbol) DO NOTHING""")
    )
    register_alpha_definition(connection, definition)
    context = RunContext(
        "b" * 40, False, config_hash(config), config.stream_id, 0, datetime.now(UTC)
    )
    store = PaperStore(paper_engine, config, context)
    live = PaperRuntime(config, definition, context.code_commit, PostgresTripStore(paper_engine))
    for offset in range(4):
        live.closed(candle(offset))
    store.save(live)
    stamp = candle(3).event_time + 2_000_000
    live.message(quote(stamp), stamp + 10_000)
    store.save(live)
    row = connection.execute(
        text("""SELECT f.qty,i.quote_asset,o.is_simulated,p.mode
        FROM fills f JOIN orders o USING(order_id)
        JOIN instruments i ON i.instrument_id=f.instrument_id
        JOIN paper_runs p USING(paper_run_id) WHERE paper_run_id=:id"""),
        dict(id=config.run_id),
    ).one()
    assert row.qty == row.qty.to_integral_value()
    assert (row.quote_asset, row.is_simulated, row.mode) == ("INR", True, "PAPER")
    live.halt("synthetic_test_end")
    store.save(live)
    artifact = tmp_path / "synthetic_fixture.json"
    artifact.write_text('{"is_synthetic":true}')
    store.finish(artifact, sha256(artifact), failed=False)
    assert (
        connection.execute(
            text("SELECT status FROM paper_runs WHERE paper_run_id=:id"), dict(id=config.run_id)
        ).scalar_one()
        == "finished"
    )
