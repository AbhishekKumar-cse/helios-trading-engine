"""007 backtest ownership and immutable terminal run evidence (149)."""

from collections.abc import Sequence

from alembic import op

revision: str = "d14900000700"
down_revision: str | None = "c11600000600"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""ALTER TABLE backtest_runs
        ADD COLUMN mode text NOT NULL DEFAULT 'BACKTEST' CHECK(mode='BACKTEST'),
        ADD COLUMN dirty boolean NOT NULL DEFAULT false,
        ADD COLUMN config_json jsonb NOT NULL DEFAULT '{}'
            CHECK(jsonb_typeof(config_json)='object'),
        ADD COLUMN artifact_sha256 text CHECK(artifact_sha256 ~ '^[0-9a-f]{64}$')""")
    for table in ("orders", "positions_snapshot", "pnl_snapshots"):
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN bt_run_id text "
            "REFERENCES backtest_runs ON DELETE RESTRICT"
        )
        op.create_index(f"ix_{table}_backtest_run", table, ["bt_run_id"])
    op.execute("""CREATE FUNCTION helios_freeze_backtest() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN IF TG_OP='DELETE' OR OLD.status IN ('finished','failed') THEN
            RAISE EXCEPTION 'terminal backtest evidence is immutable'; END IF;
        RETURN NEW; END; $$""")
    op.execute("""CREATE TRIGGER terminal_backtest_is_immutable BEFORE UPDATE OR DELETE
        ON backtest_runs FOR EACH ROW EXECUTE FUNCTION helios_freeze_backtest()""")


def downgrade() -> None:
    for table in ("orders", "positions_snapshot", "pnl_snapshots"):
        op.execute(
            f"DO $$ BEGIN IF EXISTS(SELECT 1 FROM {table} WHERE bt_run_id IS NOT NULL) "
            "THEN RAISE EXCEPTION 'backtest ownership requires migration 007'; END IF; END $$"
        )
    op.execute("""DO $$ BEGIN IF EXISTS(SELECT 1 FROM backtest_runs WHERE config_json <> '{}')
        THEN RAISE EXCEPTION 'persisted backtests require migration 007'; END IF; END $$""")
    op.execute("DROP TRIGGER terminal_backtest_is_immutable ON backtest_runs")
    op.execute("DROP FUNCTION helios_freeze_backtest()")
    for table in ("orders", "positions_snapshot", "pnl_snapshots"):
        op.drop_column(table, "bt_run_id")
    for column in ("mode", "dirty", "config_json", "artifact_sha256"):
        op.drop_column("backtest_runs", column)
