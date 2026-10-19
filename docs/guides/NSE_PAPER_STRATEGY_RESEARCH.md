# Paper-inspired NSE strategy integration

The three fixed prototypes now run through the shared DSL/evaluator, strategy,
risk, OMS, simulated venue, INR ledger, reference costs, stress, gates and registry.
They remain exploratory quantitative definitions, not promoted alphas. Existing
TRAIN-only model files are copied solely for required evaluator lineage; these
definitions neither consume ML predictions nor retrain a model.

`nse_paper_minute_features_v1` represents binary long/flat states. The opt-in
`paper_state_change_v1` mode issues targets only when that state changes. The
actual filled whole-share quantity is held until exit. Every close-confirmed
decision executes at the next observed opening. Entry sizing uses the known
decision close; no future opening sizes the order. An entry blocked by risk is
not silently retried on every following minute. At most one entry per session
is allowed. The final calendar-known exit remains the 15:29 opening.

The default every-bar strategy, legacy policy hashes, crypto research and all
existing results retain their previous behavior. Changing this execution mode
or the signal input without matching preregistration is rejected. The evaluator
also recomputes each signal-input digest before any registry transaction.

History uses strictly previous scheduled sessions. Missing, quarantined and
short-session observations invalidate history rather than being replaced by
older observations. ORB ranks use the first five completed volumes across the
41-company conditional cohort. This is still an ex-post source cohort, not proof
of historically tradable availability. Unavailable sessions are excluded with
an explicit reason; they are never included as zero-return days.

For a new protocol and exclusive output ID, in the documented WSL environment:

```bash
python scripts/run_nse_paper_research.py \
  --snapshot data/equities/nifty50_repaired/20261018_v2 \
  --model-lineage reports_out/equity_research/nse_minute_breadth1/ml \
  --round-id nse_NEW_UNIQUE_ID --symbols RELIANCE --workers 4
```

Replace the ID with lowercase letters, numbers and underscores. The runner
archives executable source and starts a fresh interpreter from that archive,
freezes the protocol before preparation, binds bars/signals/ranking history in a
snapshot and preregisters all attempts before scoring. Uncommitted development
source remains `dirty=true`; a later commit must not relabel old measurements.
Existing directories are exclusive and must not be rerun or overwritten.

Reconcile a completed round using new verification output paths:

```bash
python scripts/verify_equity_round.py nse_NEW_UNIQUE_ID --output NEW_checks.json
python scripts/verify_nse_paper_schedule.py nse_NEW_UNIQUE_ID \
  --output NEW_schedule_checks.json \
  --training-records reports_out/equity_research/nse_papers_train1/session_records.json
```

The first verifier reconciles registry identity, preregistration, source hashes,
whole-share ledger, statutory settlements, normal/stressed metrics and every
gate. The second independently checks the decision schedule, fixed quantities,
following-opening prices, both cost scenarios, source/ranking history and parity
with the previously frozen TRAIN decisions. Bulk source data, models and
execution artifacts remain local and outside Git.

The October 19 bounded round is `nse_papers_shared1`: all three candidates ran
on RELIANCE's full frozen January 9–June 30, 2026 VALID window. Those dates were
previously exposed, so this is integration evidence and exploratory measurement,
not fresh independent confirmation. Every outcome is retained. It does not
claim shared-engine replay on all 41 companies.

Minute gate units and thresholds are unchanged. Sparse strategies can fail the
existing per-bar turnover gate. G7 remains false because raw unit/vintage,
causal availability and executable liquidity/cost evidence are unresolved. The
certification assessment is reproduced with:

```bash
python scripts/assess_nse_certification.py \
  --certificate reports_out/equity_research/nse_costaware_train1/certification_summary.json \
  --snapshot data/equities/nifty50_repaired/20261018_v2 \
  --output NEW_assessment_directory
```

This verifies all minute-file and reference-body hashes, preserves audit source
and documentation/refusal receipts, and reports unresolved obligations. It does
not issue a positive certificate from documentary evidence or release source
exclusions. Public OHLCV, daily references and published fee schedules do not
supply missing raw-minute vintage, receipt-time history, account acceptance or
executable fill observations. No TEST access, promotion or real order is involved.

The subsequent [longer-horizon TRAIN follow-up](../research/nse_horizons_20261019/REPORT.md)
fits three fixed LightGBM targets using January-August, calibrates September and
screens October 9-December 31 within TRAIN. All three remain below the fixed
21 bps expected-return hurdle and make no entries. This is a separate diagnostic,
not an eligible alpha or additional shared-evaluator result. Reproduce only into
a new exclusive directory with `scripts/research_nse_horizons.py`, then run
`scripts/verify_nse_horizons.py`; the verifier accepts zero-entry rounds only.
