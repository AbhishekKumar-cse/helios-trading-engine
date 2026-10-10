"""005 simulated trading persistence (step 097).

The checklist's original number 004 is already used for experiment linkage.
No existing migration or research evidence is rewritten. Runtime components are
implemented in later steps; creating these tables does not execute any orders.
Audit rows are insert-only; hash chaining and time partitioning remain future work.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b41f09700500"
down_revision: str | None = "72ac7ed56ff4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "strategies",
    "risk_limits",
    "backtest_runs",
    "orders",
    "fills",
    "positions_snapshot",
    "pnl_snapshots",
    "risk_events",
    "audit_events",
)

DDL = """
CREATE TABLE strategies (
    strategy_id text PRIMARY KEY,
    alpha_id text NOT NULL, alpha_version integer NOT NULL,
    params_json jsonb NOT NULL CHECK (jsonb_typeof(params_json) = 'object'),
    code_commit text NOT NULL CHECK (length(code_commit) > 0),
    status text NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT','ACTIVE','HALTED','ARCHIVED')),
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (alpha_id, alpha_version) REFERENCES alpha_definitions(alpha_id, version)
        ON DELETE RESTRICT
);
CREATE TABLE risk_limits (
    limit_set_id text PRIMARY KEY, scope text NOT NULL,
    version integer NOT NULL CHECK (version > 0),
    limits jsonb NOT NULL CHECK (jsonb_typeof(limits) = 'object'),
    author text NOT NULL, effective_from timestamptz NOT NULL,
    hash text NOT NULL UNIQUE CHECK (hash ~ '^[0-9a-f]{64}$'),
    UNIQUE (scope, version)
);
CREATE TABLE backtest_runs (
    bt_run_id text PRIMARY KEY,
    experiment_id integer NOT NULL REFERENCES experiments ON DELETE RESTRICT,
    strategy_id text NOT NULL REFERENCES strategies ON DELETE RESTRICT,
    data_snapshot_id text NOT NULL REFERENCES data_snapshots(snapshot_id) ON DELETE RESTRICT,
    code_commit text NOT NULL CHECK (length(code_commit) > 0),
    config_hash text NOT NULL CHECK (config_hash ~ '^[0-9a-f]{64}$'),
    seed bigint NOT NULL CHECK (seed >= 0 AND seed <= 4294967295),
    fill_model_ref text NOT NULL, cost_model_ref text NOT NULL, results_ref text,
    status text NOT NULL DEFAULT 'planned'
        CHECK (status IN ('planned','running','finished','failed')),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE orders (
    order_id text PRIMARY KEY,
    client_order_id text NOT NULL UNIQUE,
    parent_id text REFERENCES orders ON DELETE RESTRICT,
    strategy_id text NOT NULL REFERENCES strategies ON DELETE RESTRICT,
    alpha_id text, alpha_version integer,
    instrument_id integer NOT NULL REFERENCES instruments ON DELETE RESTRICT,
    side text NOT NULL CHECK (side IN ('BUY','SELL')),
    order_type text NOT NULL CHECK (order_type IN ('MARKET','LIMIT')),
    price numeric(38,18), qty numeric(38,18) NOT NULL,
    remaining_qty numeric(38,18) NOT NULL, filled_qty numeric(38,18) NOT NULL DEFAULT 0,
    avg_fill_px numeric(38,18),
    tif text NOT NULL CHECK (tif IN ('GTC','IOC','FOK')),
    status text NOT NULL CHECK (status IN
        ('NEW','PENDING_NEW','ACK','PARTIALLY_FILLED','FILLED','PENDING_CANCEL',
         'CANCELLED','REJECTED','EXPIRED','PENDING_AMEND')),
    reject_reason text, ts_created bigint NOT NULL CHECK (ts_created >= 0),
    ts_submitted bigint, ts_ack bigint, ts_terminal bigint,
    venue_order_id text, venue_id text NOT NULL,
    is_simulated boolean NOT NULL DEFAULT true CHECK (is_simulated),
    limits_snapshot_hash text NOT NULL REFERENCES risk_limits(hash) ON DELETE RESTRICT,
    CHECK (qty > 0 AND qty < 'Infinity'::numeric),
    CHECK (remaining_qty >= 0 AND filled_qty >= 0 AND remaining_qty + filled_qty <= qty),
    CHECK (price IS NULL OR (price > 0 AND price < 'Infinity'::numeric)),
    CHECK (order_type <> 'LIMIT' OR price IS NOT NULL),
    CHECK (avg_fill_px IS NULL OR (avg_fill_px > 0 AND avg_fill_px < 'Infinity'::numeric)),
    CHECK ((alpha_id IS NULL) = (alpha_version IS NULL)),
    FOREIGN KEY (alpha_id, alpha_version) REFERENCES alpha_definitions(alpha_id, version)
        ON DELETE RESTRICT,
    UNIQUE (order_id, instrument_id, side)
);
CREATE TABLE fills (
    fill_id text PRIMARY KEY, order_id text NOT NULL,
    instrument_id integer NOT NULL, side text NOT NULL,
    price numeric(38,18) NOT NULL CHECK (price > 0 AND price < 'Infinity'::numeric),
    qty numeric(38,18) NOT NULL CHECK (qty > 0 AND qty < 'Infinity'::numeric),
    liquidity_flag text NOT NULL CHECK (liquidity_flag IN ('MAKER','TAKER')),
    fee numeric(38,18) NOT NULL CHECK (fee >= 0 AND fee < 'Infinity'::numeric),
    ts_venue bigint NOT NULL CHECK (ts_venue >= 0),
    ts_received bigint NOT NULL CHECK (ts_received >= 0),
    counterparty_ref text, venue_id text NOT NULL,
    FOREIGN KEY (order_id, instrument_id, side)
        REFERENCES orders(order_id, instrument_id, side) ON DELETE RESTRICT
);
CREATE TABLE positions_snapshot (
    scope text NOT NULL, instrument_id integer NOT NULL REFERENCES instruments ON DELETE RESTRICT,
    ts bigint NOT NULL CHECK (ts >= 0),
    strategy_id text REFERENCES strategies ON DELETE RESTRICT,
    net_qty numeric(38,18) NOT NULL, avg_cost numeric(38,18) NOT NULL,
    realised_pnl numeric(38,18) NOT NULL, unrealised_pnl numeric(38,18) NOT NULL,
    mark_px numeric(38,18) NOT NULL CHECK (mark_px > 0 AND mark_px < 'Infinity'::numeric),
    PRIMARY KEY (scope, instrument_id, ts)
);
CREATE TABLE pnl_snapshots (
    scope text NOT NULL, ts bigint NOT NULL CHECK (ts >= 0),
    strategy_id text REFERENCES strategies ON DELETE RESTRICT,
    realised numeric(38,18) NOT NULL, unrealised numeric(38,18) NOT NULL,
    fees numeric(38,18) NOT NULL CHECK (fees >= 0 AND fees < 'Infinity'::numeric),
    total numeric(38,18) NOT NULL,
    gross_exposure numeric(38,18) NOT NULL CHECK (gross_exposure >= 0),
    net_exposure numeric(38,18) NOT NULL, cash numeric(38,18) NOT NULL,
    CHECK (total = realised + unrealised - fees),
    PRIMARY KEY (scope, ts)
);
CREATE TABLE risk_events (
    event_id text PRIMARY KEY, ts bigint NOT NULL CHECK (ts >= 0),
    type text NOT NULL CHECK (type IN ('LIMIT_BREACH','ORDER_REJECTED','RATE_ABNORMAL',
        'KILL_SWITCH_ARMED','KILL_SWITCH_TRIPPED','BREAKER_TRIPPED','BREAKER_RESET',
        'FEED_DEGRADED','RECONCILIATION_BREAK')),
    severity text NOT NULL CHECK (severity IN ('INFO','WARNING','ERROR','CRITICAL')),
    reason_code text NOT NULL, subject_ref text NOT NULL,
    limits_snapshot_hash text NOT NULL REFERENCES risk_limits(hash) ON DELETE RESTRICT,
    actor text, order_id text REFERENCES orders ON DELETE RESTRICT
);
CREATE TABLE audit_events (
    audit_id bigserial PRIMARY KEY, ts bigint NOT NULL CHECK (ts >= 0),
    actor text NOT NULL, action text NOT NULL, subject text NOT NULL,
    before_hash text, after_hash text, chain_hash text, justification text,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(payload) = 'object')
);
"""


def upgrade() -> None:
    op.execute(DDL)
    # PostgreSQL NUMERIC supports NaN; precision alone does not reject it.
    for table, columns in {
        "orders": ("price", "qty", "remaining_qty", "filled_qty", "avg_fill_px"),
        "fills": ("price", "qty", "fee"),
        "positions_snapshot": ("net_qty", "avg_cost", "realised_pnl", "unrealised_pnl", "mark_px"),
        "pnl_snapshots": (
            "realised",
            "unrealised",
            "fees",
            "total",
            "gross_exposure",
            "net_exposure",
            "cash",
        ),
    }.items():
        op.create_check_constraint(
            f"{table}_finite_values",
            table,
            " AND ".join(f"{column} <> 'NaN'::numeric" for column in columns),
        )
    for table in ("risk_limits", "fills", "positions_snapshot", "pnl_snapshots", "audit_events"):
        op.execute(f"""CREATE TRIGGER {table}_is_insert_only
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION helios_block_change()""")
    for table, column in (
        ("orders", "strategy_id"),
        ("fills", "order_id"),
        ("backtest_runs", "experiment_id"),
        ("risk_events", "ts"),
    ):
        op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
