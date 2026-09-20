"""004 experiments carry their parameters, and every result names one (step 068).

Two changes:

1. `experiments.params` — the settings the experiment was registered with, stored next to the
   hypothesis. Registering "momentum works" means little; registering it together with the
   lookbacks and thresholds that were going to be tried means a lot.
2. `alpha_results.experiment_id` — **required**. A measurement must belong to a question that
   was written down first. Without this, an idea can be measured fifty ways and only the
   flattering run gets a story attached afterwards.

The new column is `NOT NULL` with no default on purpose: it is added while the table is
empty, and there is no honest value to give an existing result that was never tied to a
question. If this migration fails because rows exist, that is the correct outcome — decide
explicitly which experiment those results belonged to.

Revision ID: 72ac7ed56ff4
Revises: 0c334908ef99
Create Date: 2026-09-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "72ac7ed56ff4"
down_revision: str | None = "0c334908ef99"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "experiments",
        sa.Column(
            "params",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
            comment="the settings this experiment was registered with, before any run",
        ),
    )

    op.add_column(
        "alpha_results",
        sa.Column(
            "experiment_id",
            sa.Integer,
            nullable=False,
            comment="the pre-registered question this measurement answers",
        ),
    )
    op.create_foreign_key(
        "alpha_results_experiment_fkey",
        "alpha_results",
        "experiments",
        ["experiment_id"],
        ["experiment_id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_alpha_results_experiment", "alpha_results", ["experiment_id"])


def downgrade() -> None:
    op.drop_index("ix_alpha_results_experiment", table_name="alpha_results")
    op.drop_constraint("alpha_results_experiment_fkey", "alpha_results", type_="foreignkey")
    op.drop_column("alpha_results", "experiment_id")
    op.drop_column("experiments", "params")
