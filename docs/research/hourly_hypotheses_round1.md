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

## Measured development outcome, 2026-10-14

All eight VALID attempts completed from clean source
`e34bc248a8ca43884471d3cefb9582299c452509`. Every attempt is **INVALID**, with
DATA_GAPS and UNAVAILABLE_AFTER_WARMUP. Net Sharpe and Fitness remain null; these
are not valid performance rejection scores and no candidate was promoted.

| Candidate | Experiment | Unavailable after warm-up | Retained run |
|---|---:|---:|---|
| hourly_h01 | 4482 | 4 | de9d791d-d8fc-4950-aace-08123bbd4d35 |
| hourly_h02 | 4483 | 24 | ce71b70a-b689-4795-ae09-659f97c5287a |
| hourly_h03 | 4484 | 24 | b2959a86-8524-499e-9132-d77e1d941aa6 |
| hourly_h04 | 4485 | 1 | e8f7916a-094c-448b-a2fd-7c1c5273d610 |
| hourly_h05 | 4486 | 47 | d2d4d070-75d5-4250-8a77-f3569f453111 |
| hourly_h06 | 4487 | 168 | 40ad929e-043a-4e45-9ed8-3d616311f7cb |
| hourly_h07 | 4488 | 167 | cff9a9a5-c1ca-43c6-9573-835b0c42c47b |
| hourly_h08 | 4489 | 168 | aad3717e-3ee6-421b-b367-98d66115c9ba |

Registered JSON artifact hashes, preregistration chronology and source lineage
were verified for every row, and standalone reports were generated from that
evidence. All experiments are FINISHED; all original version-1 definitions remain
immutable. TEST-access count stays zero. No prices, missing hours or unavailable
signals were filled or dropped to make these simulations pass. A separately
documented data-quality/execution policy is needed before performance conclusions.
