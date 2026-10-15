# Frozen minute round final selection

`scripts/review_minute_selection.py` reviews the latest retained VALID attempt
for every frozen version-one minute baseline, quantitative hypothesis and ML
alpha. It verifies saved artifact hashes, alpha/version/family, split and source
commit/configuration/snapshot/seed. Missing, truncated or inconsistent evidence
fails visibly. No observation loader, model fitting or TEST evaluator is invoked.

The shortlist uses the existing `alpha.final_test` eligibility and ranking rules:
clean VALID evidence, accepted complete G1–G6, recomputed passing metrics, unused
TEST budget, then at most two candidates ranked by Fitness. Numerical Sharpe
alone does not qualify an otherwise rejected candidate. A newer version requires
a separately declared round; an earlier success cannot hide a later failure.

From clean source run:

```bash
python scripts/review_minute_selection.py --finalize-skip
```

Finalization is permitted only for an unchanged empty shortlist. It journals
REJECTED selection decisions through the existing hash-verified, append-only
registry API in one repeatable-read transaction. It never rewrites measurement
status or metrics. An INVALID measurement remains INVALID. All twelve decisions
must succeed together. Repetition with the same evidence is idempotent.

The unique ignored `reports_out/minute_selection/<UUID>/review.json` records the
source commit, evidence, exclusions, global TEST count and resulting decisions.
An eligible shortlist instead requires a frozen TEST experiment and the existing
reservation-before-loader protocol; this review command cannot consume TEST or
silently promote candidates. The dashboard displays minute selection separately
from measurement status using `minute_round1`.
