"""008 PAPER ownership and immutable terminal session evidence."""

from collections.abc import Sequence

from alembic import op

revision: str = "e16000000800"
down_revision: str | None = "d14900000700"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""CREATE TABLE paper_runs (
        paper_run_id text PRIMARY KEY,
        experiment_id integer NOT NULL REFERENCES experiments ON DELETE RESTRICT,
        strategy_id text NOT NULL UNIQUE REFERENCES strategies ON DELETE RESTRICT,
        mode text NOT NULL CHECK(mode='PAPER'),
        is_simulated boolean NOT NULL CHECK(is_simulated),
        stream_id text NOT NULL UNIQUE CHECK(stream_id ~ '^[0-9a-f]{64}$'),
        code_commit text NOT NULL CHECK(code_commit ~ '^[0-9a-f]{40}$'),
        dirty boolean NOT NULL CHECK(NOT dirty),
        config_hash text NOT NULL CHECK(config_hash ~ '^[0-9a-f]{64}$'),
        config_json jsonb NOT NULL CHECK(jsonb_typeof(config_json)='object'),
        status text NOT NULL CHECK(status IN ('running','finished','failed')),
        artifact_ref text, artifact_sha256 text CHECK(artifact_sha256 ~ '^[0-9a-f]{64}$'),
        created_at timestamptz NOT NULL DEFAULT now()
    )""")
    for table in ("orders", "positions_snapshot", "pnl_snapshots"):
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN paper_run_id text REFERENCES paper_runs "
            "ON DELETE RESTRICT, ADD CONSTRAINT " + table + "_single_run_owner "
            "CHECK(paper_run_id IS NULL OR bt_run_id IS NULL)"
        )
        op.create_index(f"ix_{table}_paper_run", table, ["paper_run_id"])
    op.execute("""CREATE FUNCTION helios_freeze_paper() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN IF TG_OP='DELETE' OR OLD.status IN ('finished','failed') THEN
            RAISE EXCEPTION 'terminal paper evidence is immutable'; END IF;
        RETURN NEW; END; $$""")
    op.execute("""CREATE TRIGGER terminal_paper_is_immutable BEFORE UPDATE OR DELETE ON paper_runs
        FOR EACH ROW EXECUTE FUNCTION helios_freeze_paper()""")


def downgrade() -> None:
    op.execute("""DO $$ BEGIN IF EXISTS(SELECT 1 FROM paper_runs)
        THEN RAISE EXCEPTION 'retained PAPER sessions require migration 008'; END IF; END $$""")
    for table in ("orders", "positions_snapshot", "pnl_snapshots"):
        op.drop_constraint(f"{table}_single_run_owner", table)
        op.drop_column(table, "paper_run_id")
    op.execute("DROP TRIGGER terminal_paper_is_immutable ON paper_runs")
    op.execute("DROP FUNCTION helios_freeze_paper()")
    op.drop_table("paper_runs")
