# Fixed minute VALID round (156)

Eleven experiments were preregistered from clean `2452824` before minute
evaluation implementation or measurements: **5598–5608**, corresponding to
`minute_b0`, `minute_b1`, `minute_b2`, then `minute_h01`–`minute_h08`.
The snapshot is
`b1799dbee6c68d72e55a8461f9701bf62744816db7dc859ebb2c5995a237277f`.
Each attempt fixes BTCUSDT, H-MINUTE/1m, version 1, one-minute horizon, seed 0,
168 warm-up rows, full accepted VALID dates and unchanged fees/G1–G6. All known
hourly results and the completed feature export were declared as prior exposure.

Three baselines reuse fixed 24-bar momentum sign, 168-bar return reversal z-score
and 168-bar taker-flow z-score. Eight fixed hypotheses reuse the hourly round's
expressions and scalar constants as distinct minute definitions: fast momentum,
momentum blend, volatility scaling, one-bar reversal, mean reversal, flow blend,
volume-shock momentum and quiet-regime reversal. Windows count minute bars here.
There is one configuration per definition, no tuning or seed selection.

`helios.alpha.minute_round` constructs these definitions and checks the complete
definition/evaluation/stage protocol against the registered experiment. It refuses
missing, changed, duplicate or consumed preregistrations. New definitions remain
separate from the immutable hourly versions. On a fresh database,
`preregister_minute(connection, snapshot_id)` writes the fixed protocol before
measurement; the actual experiments above must never be registered again.

After committing implementation, execute once from clean source:

```bash
/home/abhi/.venvs/helios/bin/python scripts/evaluate_minute.py
```

This atomically registers the eleven definitions, then measures them sequentially.
Each finished result, including INVALID or poor performance, is retained. A
failure is recorded and stops the round; the manifest prevents an automatic
retry. Outcomes and hashed evidence are under `reports_out/minute_round1/`.
Do not delete those artifacts to rerun the round.

The same split simulator, costs, Fitness, stability, IC and gates serve hourly
and minute definitions. `EvaluationConfig(interval="1m")` selects the minute
feature partitions, split family, label grid and 525,600 annualization. TRAIN
alone calibrates VALID volatility regimes; no thresholds fit VALID returns.
The minute TRAIN regime-evaluation path is refused until an earlier calibration
policy is supplied. The ordinary hourly defaults retain their existing behavior.

TEST still reserves access before its loader. This round invokes VALID only and
never touches TEST, changes a split or promotes a candidate. A clean-source
result is not a deployment approval; the retained gates and later selection
policy remain authoritative. The following step's cost-reality note records
measured outcomes without rerunning or optimizing candidates.

## Retained outcome (2026-10-15)

All eleven attempts finished from clean source
`68d66a1012f4c0916e4ce3664406fb2e2ae6d090`. Every candidate is **REJECTED**;
none is promoted. The companion
[`minute_round1_results.json`](../research/minute_round1_results.json) records
each experiment/run ID, measured metrics, gate outcomes and artifact checksum.
The large evaluation artifacts remain outside Git. Hash verification also checks
preregistration preceded measurement, the minute annualization and TRAIN-only
regime calibration. TEST access remains zero. The original hourly research and
all existing feature files remain unchanged.
