"""003 make the registry insert-only (step 062).

The registry is worthless if a disappointing number can be quietly corrected later. This
migration installs database triggers so that, for the tables that record *what happened*,
UPDATE and DELETE are simply refused:

- `alpha_definitions` - what an idea is, fixed per version
- `alpha_results`     - what an evaluation produced
- `data_snapshots`    - which bytes a result used

A policy written only in Python protects the code that remembers to call it. A trigger
protects the data from every route into the database: a script, a teammate, a stray SQL
statement typed into Adminer, or a future version of our own code.

**How things still change, without editing history**

- a change to an idea is a **new version** of the definition;
- a re-run is a **new result row** (its own run_id);
- a promotion or rejection is recorded by **inserting** a later result row for that alpha
  version, never by rewriting the earlier one;
- a mistake stays visible, and is corrected by adding the correction.

Dropping a table still works (Alembic's own downgrade needs that), because a trigger only
guards the rows, not the table itself.

Revision ID: 0c334908ef99
Revises: 4208a0a5ffa7
Create Date: 2026-09-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0c334908ef99"
down_revision: str | None = "4208a0a5ffa7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROTECTED = ("alpha_definitions", "alpha_results", "data_snapshots")

BLOCK_FUNCTION = """
CREATE OR REPLACE FUNCTION helios_block_change() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'table % is insert-only: % is not allowed', TG_TABLE_NAME, TG_OP
        USING HINT = 'record the change by inserting a new row (a new version or a new run)',
              ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.execute(BLOCK_FUNCTION)
    for table in PROTECTED:
        op.execute(f"""
            CREATE TRIGGER {table}_is_insert_only
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION helios_block_change()
        """)


def downgrade() -> None:
    for table in PROTECTED:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_is_insert_only ON {table}")
    op.execute("DROP FUNCTION IF EXISTS helios_block_change()")
