"""006 nullable undefined metrics and immutable evaluation evidence (116)."""

from collections.abc import Sequence

from alembic import op

revision: str = "c11600000600"
down_revision: str | None = "b41f09700500"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE alpha_results ADD COLUMN evaluation_json jsonb")
    for column in ("sharpe", "annual_return", "turnover", "fitness"):
        op.execute(f"ALTER TABLE alpha_results ALTER COLUMN {column} DROP NOT NULL")
    op.execute("ALTER TABLE alpha_results DROP CONSTRAINT alpha_results_status_known")
    op.execute(
        "ALTER TABLE alpha_results ADD CONSTRAINT alpha_results_status_known "
        "CHECK (status IN ('EVALUATED','PROMOTED','REJECTED','ARCHIVED','INVALID'))"
    )
    op.execute("ALTER TABLE alpha_results DROP CONSTRAINT alpha_results_periods_positive")
    op.execute(
        "ALTER TABLE alpha_results ADD CONSTRAINT alpha_results_periods_positive "
        "CHECK (periods > 0 OR (status='INVALID' AND periods >= 0))"
    )
    op.execute(
        "ALTER TABLE alpha_results ADD CONSTRAINT alpha_results_defined_accounting "
        "CHECK (status='INVALID' OR (annual_return IS NOT NULL AND turnover IS NOT NULL))"
    )
    op.execute(
        "ALTER TABLE alpha_results ADD CONSTRAINT alpha_results_invalid_evidence "
        "CHECK (status <> 'INVALID' OR (evaluation_json IS NOT NULL "
        "AND COALESCE(evaluation_json->>'status'='INVALID', false) AND sharpe IS NULL "
        "AND annual_return IS NULL AND turnover IS NULL AND fitness IS NULL))"
    )
    op.execute(
        "ALTER TABLE alpha_results ADD CONSTRAINT alpha_results_promoted_defined "
        "CHECK (status <> 'PROMOTED' OR (sharpe IS NOT NULL AND fitness IS NOT NULL))"
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_result_test_reservation ON alpha_results "
        "((evaluation_json->>'test_access_id')) WHERE "
        "evaluation_json->>'test_access_id' IS NOT NULL"
    )


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM alpha_results WHERE status='INVALID' "
        "OR sharpe IS NULL OR fitness IS NULL OR evaluation_json IS NOT NULL) "
        "THEN RAISE EXCEPTION 'new result evidence requires migration 006'; END IF; END $$"
    )
    op.execute("DROP INDEX IF EXISTS ix_result_test_reservation")
    for name in (
        "defined_accounting",
        "invalid_evidence",
        "promoted_defined",
        "status_known",
        "periods_positive",
    ):
        op.execute(f"ALTER TABLE alpha_results DROP CONSTRAINT alpha_results_{name}")
    op.execute(
        "ALTER TABLE alpha_results ADD CONSTRAINT alpha_results_status_known "
        "CHECK (status IN ('EVALUATED','PROMOTED','REJECTED','ARCHIVED'))"
    )
    op.execute(
        "ALTER TABLE alpha_results ADD CONSTRAINT alpha_results_periods_positive "
        "CHECK (periods > 0)"
    )
    for column in ("sharpe", "annual_return", "turnover", "fitness"):
        op.execute(f"ALTER TABLE alpha_results ALTER COLUMN {column} SET NOT NULL")
    op.execute("ALTER TABLE alpha_results DROP COLUMN evaluation_json")
