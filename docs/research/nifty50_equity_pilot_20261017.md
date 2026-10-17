# Nifty 50 equity pilot — 2026-10-17

Downloaded daily, hourly and recent minute history for all 50 companies in the
official constituent CSV fetched on 2026-10-17. Prices are Yahoo-distributed
NSE-listed equity data in INR, not official NSE historical price files. The
original crypto research and registry were not modified.

The exact measured counts, model scores, exclusions and fingerprints are generated
in [the verified summary](nifty50_equity_pilot_20261017.json). Bulk source responses,
processed bars, model text files, predictions and source archives remain local
and ignored by Git. [The guide](../guides/NIFTY50_EQUITY_RESEARCH.md) documents the
commands, date windows, availability policy and next data requirements.

One pooled daily LightGBM and one pooled hourly LightGBM were fitted. Each used
49 companies: JIOFIN has no daily TRAIN history in the frozen window; TMPV has
insufficient usable hourly TRAIN samples after its vendor symbol-history cutoff.
All 50 companies' available data was downloaded. The exclusions apply to these
fits, not to download coverage. No prices were fabricated before listing or filled
across missing observations.

The first attempt completed the daily fit but failed hourly eligibility because
opening bars frequently had zero reported volume. That partial attempt and its
daily model/predictions remain preserved. Before the first hourly model fit,
hourly feature windows were shortened from 20 bars to 1/2/3 bars while keeping
zero-volume and discontinuity exclusions. The second attempt repeated the same
daily fit and completed hourly training. Daily metrics were identical. This was
not a hyperparameter search or a choice made from hourly performance.

VALID selected early stopping; these are development scores. Daily AUC is close
to random ranking and hourly AUC is below it. Neither model establishes a useful
tradable alpha. No TEST observations were supplied to either fit or displayed in
daily/hourly charts. No TEST performance, registry promotion, costs, taxes,
slippage, strategy returns or live orders are claimed.

Current constituent selection introduces survivorship bias; it cannot support a
historical Nifty index performance claim. Yahoo adjustments, ticker renames,
demergers, historical membership, special sessions and data completeness still
need stronger independently verified data before equity strategy claims.

Recent minute history is ingestion evidence only. It contains gaps and is too
short for substantial minute-model research. A suitable historical provider or
authorized broker feed is the next prerequisite for that work.

Verification completed: repository-wide Ruff lint/format and strict mypy passed;
19 equity/data/dashboard/simulation tests and 33 existing registry/PAPER/crypto ML
regressions passed. Both serialized LightGBM models were independently reloaded,
TRAIN/VALID sample hashes reproduced, and every saved VALID prediction matched
within absolute tolerance 1e-12. The actual browser displayed all three downloaded
bar counts, the equity price chart and both retained model measurements.
