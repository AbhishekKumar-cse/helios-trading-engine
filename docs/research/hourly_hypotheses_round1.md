# Fixed hourly development round

Eight hypotheses in `helios.alpha.hourly_hypotheses` cover fast momentum,
daily/fast momentum blend, volatility-scaled momentum, one-hour reversal,
slow mean reversal, taker-flow blend, volume-shock momentum and quiet-regime
reversal. All expressions and scalar constants are fixed before their attempts.
This first round is BTCUSDT hourly; cross-sectional hypotheses require a separate
universe-aware evaluator and are not substituted with a single-coin rank.

Step 127 creates eight experiment rows atomically before any candidate evaluation.
Earlier baseline, linear and LightGBM VALID results are already known and this
exposure is declared. This is development research, not blind held-out inference.
The fixed protocol is version 1, feature set v1, one-hour horizon, seed 0, 168
warm-up rows, accepted splits/fees/gates, VALID only, no parameter search.
All outcomes, including INVALID and poor scores, must be retained. No promotion
is automatic. TEST remains untouched. Later YAML registration must match each
preregistered definition exactly except its separately recorded source commit.

Actual preregistration: experiments **4482–4489**, respectively hourly_h01–h08,
were written from clean source `1da809b` before YAML registration or any candidate
measurement. `configs/alphas/hourly/` contains the eight version-1 definitions.
The loader rejects missing, extra or changed YAMLs; registration verifies the
database preregistration and inserts all definitions in one transaction. Fixture
tests use separate identifiers so they do not modify actual research records.

`scripts/evaluate_hourly.py` binds each YAML and immutable registry version to its
own experiment, enforces the fixed VALID configuration, and rejects a repeated
round once attempts are retained. Eight isolated process jobs use the existing
strict simulator. An immutable outcome manifest links every attempt to its
database result and hashed JSON evidence. Measurement starts after committing the
verified runner so reported source lineage is clean. There is no parameter change
or v2 selection in this round. INVALID is a retained data-validity outcome, not an
invented low score or evidence of profitability.
