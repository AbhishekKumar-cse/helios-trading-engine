"""002 the alpha registry (step 061).

Four tables that make alpha research auditable:

- `alpha_definitions`   what an idea *is*, fixed per version and never edited
- `alpha_results`       one row per evaluation run, with its metrics and gate outcomes
- `alpha_gate_config`   the gate thresholds in force, versioned and dated
- `test_set_access`     every time the TEST period was touched, by whom and why

The point of separating them: a definition may be evaluated many times (different splits,
different data snapshots, different gate versions), and a result is only meaningful when you
can say which definition, which data and which thresholds produced it. Step 062 adds
triggers so definitions and results cannot be changed or deleted after the fact.

Revision ID: 4208a0a5ffa7
Revises: 8fcab6513ac4
Create Date: 2026-09-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "4208a0a5ffa7"
down_revision: str | None = "8fcab6513ac4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# metrics are ratios and fractions: exact decimals, never floating point
METRIC = sa.Numeric(20, 10)

HORIZON_FAMILIES = "('H-HOURLY', 'H-MINUTE', 'H-SECOND', 'H-MICRO')"
SPLITS = "('train', 'valid', 'test')"
STATUSES = "('EVALUATED', 'PROMOTED', 'REJECTED', 'ARCHIVED')"
PROVENANCE = "('human', 'ml', 'genetic', 'literature')"


def upgrade() -> None:
    op.create_table(
        "alpha_definitions",
        sa.Column("alpha_id", sa.Text, nullable=False),
        sa.Column(
            "version",
            sa.Integer,
            nullable=False,
            comment="a change to the idea is a new version, never an edit of the old one",
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("provenance", sa.Text, nullable=False),
        sa.Column(
            "spec_json",
            postgresql.JSONB,
            nullable=False,
            comment="the complete recipe: features, parameters, position rule",
        ),
        sa.Column("feature_set_version", sa.Text, nullable=False),
        sa.Column("horizon_family", sa.Text, nullable=False),
        sa.Column(
            "horizon_periods",
            sa.Integer,
            nullable=False,
            comment="how far ahead the idea predicts, in periods of its family",
        ),
        sa.Column("author", sa.Text, nullable=False),
        sa.Column("code_commit", sa.Text, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("alpha_id", "version", name="alpha_definitions_pkey"),
        sa.CheckConstraint("version > 0", name="alpha_definitions_version_positive"),
        sa.CheckConstraint("horizon_periods > 0", name="alpha_definitions_horizon_positive"),
        sa.CheckConstraint(
            f"horizon_family IN {HORIZON_FAMILIES}", name="alpha_definitions_family_known"
        ),
        sa.CheckConstraint(
            f"provenance IN {PROVENANCE}", name="alpha_definitions_provenance_known"
        ),
        sa.CheckConstraint("length(code_commit) = 40", name="alpha_definitions_commit_full"),
        comment="What each alpha is. Immutable per version (see migration 003).",
    )

    op.create_table(
        "alpha_gate_config",
        sa.Column("config_id", sa.Text, primary_key=True, comment="e.g. gates_v1"),
        sa.Column("sharpe_min", METRIC, nullable=False),
        sa.Column("fitness_min", METRIC, nullable=False),
        sa.Column("fitness_turnover_floor", METRIC, nullable=False),
        sa.Column("turnover_min", METRIC, nullable=False),
        sa.Column("turnover_max", METRIC, nullable=False),
        sa.Column("require_out_of_sample", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("stability_min_positive_fraction", METRIC, nullable=False),
        sa.Column("cost_stress_multiplier", METRIC, nullable=False),
        sa.Column("cost_stress_sharpe_min", METRIC, nullable=False),
        sa.Column("extra", postgresql.JSONB, nullable=True),
        sa.Column(
            "config_hash",
            sa.Text,
            nullable=False,
            comment="fingerprint of configs/gates_*.yaml, so the file and the row cannot drift",
        ),
        sa.Column("author", sa.Text, nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("turnover_min < turnover_max", name="alpha_gate_config_turnover_range"),
        sa.CheckConstraint("fitness_turnover_floor > 0", name="alpha_gate_config_floor_positive"),
        sa.CheckConstraint(
            "cost_stress_multiplier >= 1", name="alpha_gate_config_stress_at_least_1"
        ),
        sa.CheckConstraint("length(config_hash) = 64", name="alpha_gate_config_hash_sha256"),
        comment="Gate thresholds in force. Changing a gate means a new row, and is audited.",
    )

    op.create_table(
        "alpha_results",
        sa.Column("run_id", sa.Text, primary_key=True, comment="uuid of one evaluation run"),
        sa.Column("alpha_id", sa.Text, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("split", sa.Text, nullable=False),
        sa.Column(
            "snapshot_id",
            sa.Text,
            sa.ForeignKey("data_snapshots.snapshot_id", ondelete="RESTRICT"),
            nullable=False,
            comment="exactly which data produced these numbers",
        ),
        sa.Column(
            "gate_config_id",
            sa.Text,
            sa.ForeignKey("alpha_gate_config.config_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # metrics, all net of costs
        sa.Column("sharpe", METRIC, nullable=False),
        sa.Column("annual_return", METRIC, nullable=False),
        sa.Column("turnover", METRIC, nullable=False),
        sa.Column("fitness", METRIC, nullable=False),
        sa.Column("max_drawdown", METRIC, nullable=True),
        sa.Column("hit_rate", METRIC, nullable=True),
        sa.Column("cost_stress_sharpe", METRIC, nullable=True, comment="Sharpe at 2x cost (G6)"),
        sa.Column("stability_positive_fraction", METRIC, nullable=True, comment="G5 evidence"),
        sa.Column("periods", sa.BigInteger, nullable=False, comment="how many periods were scored"),
        sa.Column(
            "gate_results",
            postgresql.JSONB,
            nullable=False,
            comment='pass/fail per gate, e.g. {"G1": true, "G2": false, ...}',
        ),
        sa.Column("status", sa.Text, nullable=False, server_default="EVALUATED"),
        # lineage: enough to reproduce the run
        sa.Column("code_commit", sa.Text, nullable=False),
        sa.Column("config_hash", sa.Text, nullable=False),
        sa.Column("seed", sa.BigInteger, nullable=False),
        sa.Column(
            "dirty",
            sa.Boolean,
            nullable=False,
            comment="true when the working folder had uncommitted changes; such a run is "
            "never reportable",
        ),
        sa.Column("runtime_seconds", METRIC, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["alpha_id", "version"],
            ["alpha_definitions.alpha_id", "alpha_definitions.version"],
            name="alpha_results_definition_fkey",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(f"split IN {SPLITS}", name="alpha_results_split_known"),
        sa.CheckConstraint(f"status IN {STATUSES}", name="alpha_results_status_known"),
        sa.CheckConstraint("turnover >= 0", name="alpha_results_turnover_not_negative"),
        sa.CheckConstraint("periods > 0", name="alpha_results_periods_positive"),
        sa.CheckConstraint(
            "hit_rate IS NULL OR (hit_rate >= 0 AND hit_rate <= 1)",
            name="alpha_results_hit_rate_fraction",
        ),
        sa.CheckConstraint(
            "stability_positive_fraction IS NULL OR "
            "(stability_positive_fraction >= 0 AND stability_positive_fraction <= 1)",
            name="alpha_results_stability_fraction",
        ),
        sa.CheckConstraint(
            "max_drawdown IS NULL OR max_drawdown <= 0",
            name="alpha_results_drawdown_not_positive",
        ),
        sa.CheckConstraint(
            "status <> 'PROMOTED' OR split <> 'train'",
            name="alpha_results_no_promotion_on_train",
        ),
        comment="One row per evaluation run. Insert-only (see migration 003).",
    )
    op.create_index("ix_alpha_results_alpha", "alpha_results", ["alpha_id", "version"])
    op.create_index("ix_alpha_results_status", "alpha_results", ["status", "split"])

    op.create_table(
        "test_set_access",
        sa.Column("access_id", sa.Integer, primary_key=True),
        sa.Column("alpha_id", sa.Text, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column(
            "snapshot_id",
            sa.Text,
            sa.ForeignKey("data_snapshots.snapshot_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("run_id", sa.Text, sa.ForeignKey("alpha_results.run_id"), nullable=True),
        sa.Column("actor", sa.Text, nullable=False, comment="who ran it"),
        sa.Column("purpose", sa.Text, nullable=False),
        sa.Column(
            "accessed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["alpha_id", "version"],
            ["alpha_definitions.alpha_id", "alpha_definitions.version"],
            name="test_set_access_definition_fkey",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("length(purpose) >= 10", name="test_set_access_purpose_not_empty"),
        comment="Every use of the TEST period. ADR-004 allows at most two per alpha version.",
    )
    op.create_index("ix_test_set_access_alpha", "test_set_access", ["alpha_id", "version"])


def downgrade() -> None:
    op.drop_index("ix_test_set_access_alpha", table_name="test_set_access")
    op.drop_table("test_set_access")
    op.drop_index("ix_alpha_results_status", table_name="alpha_results")
    op.drop_index("ix_alpha_results_alpha", table_name="alpha_results")
    op.drop_table("alpha_results")
    op.drop_table("alpha_gate_config")
    op.drop_table("alpha_definitions")
