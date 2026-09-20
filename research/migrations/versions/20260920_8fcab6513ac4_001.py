"""001 instruments, data_snapshots, experiments (step 057).

The three tables that make a result explainable months later:

- `instruments`    which coins exist, their price and size steps, and when they were listed
- `data_snapshots` exactly which files a result was computed from, with their checksum
- `experiments`    the question being asked, **written down before** the answer is known

`data_snapshots` and `experiments` are meant to be written once and never edited; step 062
adds database triggers that enforce that for the alpha tables as well.

Revision ID: 8fcab6513ac4
Revises:
Create Date: 2026-09-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8fcab6513ac4"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# prices and sizes are exact decimals, never floats: 0.1 + 0.2 must not become 0.30000000000000004
DECIMAL = sa.Numeric(38, 18)


def upgrade() -> None:
    op.create_table(
        "instruments",
        sa.Column("instrument_id", sa.Integer, primary_key=True),
        sa.Column("symbol", sa.Text, nullable=False, unique=True),
        sa.Column("venue", sa.Text, nullable=False, server_default="binance_spot"),
        sa.Column("base_asset", sa.Text, nullable=False),
        sa.Column("quote_asset", sa.Text, nullable=False),
        sa.Column("tick_size", DECIMAL, nullable=False),
        sa.Column("lot_size", DECIMAL, nullable=False),
        sa.Column(
            "first_available_date",
            sa.Date,
            nullable=False,
            comment="first day the venue has data; used by universe_on() so a coin is never "
            "traded before it was listed",
        ),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("tick_size > 0", name="instruments_tick_size_positive"),
        sa.CheckConstraint("lot_size > 0", name="instruments_lot_size_positive"),
        sa.CheckConstraint("symbol = upper(symbol)", name="instruments_symbol_upper"),
        comment="Reference data for every tradable pair.",
    )

    op.create_table(
        "data_snapshots",
        sa.Column(
            "snapshot_id",
            sa.Text,
            primary_key=True,
            comment="sha256 over the sorted list of file names and their checksums",
        ),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("interval", sa.Text, nullable=False),
        sa.Column(
            "symbols",
            sa.dialects.postgresql.JSONB,
            nullable=False,
            comment="the coins included, as a JSON array",
        ),
        sa.Column("first_open_time", sa.BigInteger, nullable=False, comment="UTC microseconds"),
        sa.Column("last_open_time", sa.BigInteger, nullable=False, comment="UTC microseconds"),
        sa.Column("file_count", sa.Integer, nullable=False),
        sa.Column("row_count", sa.BigInteger, nullable=False),
        sa.Column("total_bytes", sa.BigInteger, nullable=False),
        sa.Column("code_commit", sa.Text, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("file_count > 0", name="data_snapshots_files_positive"),
        sa.CheckConstraint("row_count > 0", name="data_snapshots_rows_positive"),
        sa.CheckConstraint(
            "last_open_time >= first_open_time", name="data_snapshots_range_ordered"
        ),
        comment="Immutable record of the exact data a result was computed from.",
    )
    op.create_index("ix_data_snapshots_created_at", "data_snapshots", ["created_at"])

    op.create_table(
        "experiments",
        sa.Column("experiment_id", sa.Integer, primary_key=True),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column(
            "hypothesis",
            sa.Text,
            nullable=False,
            comment="what we expect to find, written before the run; an experiment whose "
            "question is written afterwards proves nothing",
        ),
        sa.Column("author", sa.Text, nullable=False),
        sa.Column(
            "pre_registered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("status", sa.Text, nullable=False, server_default="planned"),
        sa.Column("code_commit", sa.Text, nullable=True),
        sa.Column("config_hash", sa.Text, nullable=True),
        sa.Column(
            "snapshot_id",
            sa.Text,
            sa.ForeignKey("data_snapshots.snapshot_id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("notes", sa.Text, nullable=True),
        sa.CheckConstraint(
            "kind IN ('alpha', 'ml', 'backtest', 'infrastructure', 'other')",
            name="experiments_kind_known",
        ),
        sa.CheckConstraint(
            "status IN ('planned', 'running', 'finished', 'abandoned')",
            name="experiments_status_known",
        ),
        sa.CheckConstraint("length(hypothesis) >= 10", name="experiments_hypothesis_not_empty"),
        comment="One row per question asked, registered before the answer is known.",
    )
    op.create_index("ix_experiments_kind_status", "experiments", ["kind", "status"])


def downgrade() -> None:
    op.drop_index("ix_experiments_kind_status", table_name="experiments")
    op.drop_table("experiments")
    op.drop_index("ix_data_snapshots_created_at", table_name="data_snapshots")
    op.drop_table("data_snapshots")
    op.drop_table("instruments")
