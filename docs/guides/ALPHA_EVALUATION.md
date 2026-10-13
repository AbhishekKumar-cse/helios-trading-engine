# Registered alpha evaluation

## One-call evaluator (116)

`helios.sim.evaluate.evaluate(alpha_id, split, experiment_id)` loads a registered
hourly expression definition and an open preregistered experiment with a snapshot.
The accepted gate row must match gates_v1.yaml. Reported runs require clean Git
state before data loading. EvaluationConfig records symbol, version, explicit
warm-up (default 168 rows), minimum periods and seed; no settings are inferred
from the first successful signal or selected by score.

The existing feature store supplies causal inputs; signals are evaluated and
its manifest/file hashes are verified against the registered bar snapshot, with
the feature build's own commit/dirty lineage retained. Signals are then
bounded, then the guarded split simulator computes positions/costs/diagnostics.
Fitness, TS IC (single-coin CS remains N/A), calibrated volatility/monthly stability,
cost stress and G1–G6 are calculated using matching lineage. Volatility cuts use
December 2017 before TRAIN, or TRAIN before VALID/TEST. Calibration excludes
off-grid rows by a recorded policy; simulation gaps are never dropped or filled.
The evaluator currently scores one configured coin (BTCUSDT by default), not an
invented five-coin portfolio. It issues no orders and never promotes automatically.

Migration 006 adds optional evaluation_json evidence and preserves INVALID
attempts with NULL metrics. Valid zero-variance ratios may remain NULL and fail
their gates. Existing rows and insert-only triggers remain unchanged. INVALID
requires explicit status evidence; normal accounting/period and promotion
constraints remain enforced. Downgrade refuses to discard any new evidence.
Availability and timestamp gaps make the attempt INVALID, not a losing strategy.

Each run writes a new UUID-named JSON artifact in reports_out/evaluations, using
exclusive creation. It contains full diagnostics, IC, cost curve, monthly/regime
evidence, net series and source/protocol metadata. alpha_results stores the exact
artifact SHA-256, protocol, validity and gate-config hash. A failed DB insert may
leave an orphan artifact; it is not a registered result and is never relabelled.
Later reporting verifies the registered hash before reading it.

TEST access is reserved/committed before loading; failures still consume the use.
The existing reservation ID is retained and checked before result insertion,
without calling record_test_result and charging another access. A unique index
prevents two new result rows from reusing one reservation. Actor and purpose are
required. No real TEST observations were used in implementation tests.

## Isolated batch evaluation (117)

`python scripts/evaluate_alphas.py --experiment-id ID --alphas baseline_b0
baseline_b1 baseline_b2 --splits valid --workers 2` evaluates the fixed registered
definitions against the already preregistered experiment. It defaults to VALID,
not TEST, and requires clean reported-run source. Each job uses a spawn-isolated
process with its own engine/config/state; no connection is shared across workers.
Requests are declared in advance, duplicates refused and outputs restored to
request order. A failed worker returns a visible error type and no invented result;
the command exits nonzero on any failure. Completed/invalid attempts remain
registered independently rather than rolling successful workers back.

## Hash-verified reports (118)

`python scripts/report_alpha.py RUN_ID` writes reports_out/ALPHA_ID/report.html
after verifying the registered artifact's SHA-256, status and snapshot. Valid
simulations show reference equity (1 + additive net P&L, not compounded NAV),
additive drawdown, actual cost curve, monthly/regime tables, gates and lineage.
Display-only curve sampling does not alter any metric. INVALID reports show
reasons and N/A rather than fake zero returns or invented equity curves.

Every rendered HTML version is archived by run ID/content hash; report.html is
only the replaceable latest presentation. Original JSON/DB evidence stays intact.
Text is HTML-escaped and identifiers validated against path traversal. No remote
chart libraries are needed. `python scripts/serve_alpha_reports.py` serves only
the generated HTML views on localhost:8766; it exposes no arbitrary files or write
routes. The three actual step-117 VALID runs under experiment 4252 are retained
as INVALID due to DATA_GAPS and UNAVAILABLE_AFTER_WARMUP: B0 has 24 affected
post-warm-up signals, B1/B2 have 168 each. These are data-validity findings, not
measured losing/profitable strategies. All used clean source 163491f and no TEST.
