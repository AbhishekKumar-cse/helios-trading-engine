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
