# Public NSE minute research

This guide records the immutable v1 study. The separate
[historical-cohort rebuild](NSE_REBUILD.md) adds effective-date membership,
full/short sessions, quarantines and an opt-in execution charge policy. Original
prices and research artifacts described below remain unchanged.

The user has no broker/data-provider account. The credential-free public
Upstox endpoint supplied 6,865,386 retained minute bars for all 50 current Nifty
companies, 2025-01-01 through 2026-06-30. Zero monthly requests failed. This is
provider-distributed NSE data, not a verified exchange tick feed or BSE data.
The public NSE quote endpoint returned HTTP 403; no workaround was attempted.

The immutable local snapshot is
`data/equities/nifty50_minutes/20261017_public_round1`. Its manifest, monthly
requests, raw responses, roster, Parquets, collector source and calendar hashes
are retained locally. Bulk prices and raw responses are ignored by Git.
See [ADR 009](../decisions/ADR-009-public-nse-minute-research.md) for scope and
the TRAIN/VALID/TEST and execution assumptions.

## Reproduction commands

Use the documented WSL environment from the repository root:

```bash
export PATH=/home/abhi/.venvs/helios/bin:/home/abhi/.local/bin:/usr/bin:/bin
python scripts/freeze_equity_round.py \
  data/equities/nifty50_minutes/20261017_public_round1 \
  --round-id nse_minute_round2_example --interval 1m --suite all \
  --research-symbols RELIANCE --workers 4
```

Use a new lowercase round ID. This command creates new experiments; it is not
a read-only view of the existing round. Never overwrite or rerun an existing
attempt silently. Frozen runtimes live under `reports_out/equity_runtime/` and
results under `reports_out/equity_research/`. They preserve dirty development
source explicitly and exclude credentials. Only TRAIN and VALID are read.

`scripts/reproduce_equity.py` is the independent archived-source replay used
for step 169. It selected an existing result with seed 169, without refitting
or creating a registry measurement. The evidence is
[nse_archived_reproduction_20261017.json](../research/nse_archived_reproduction_20261017.json).

The lab at `http://localhost:8501/?page=equities` shows public minute history,
completed shared-engine research reports and model fit/calibration counts.
Select RELIANCE for the minute execution benchmark. All 50 stocks contribute
to the minute TRAIN model; the other 49 do not have minute execution outcomes
in this first benchmark.

All four retained rounds are complete: 600 hourly company measurements and
12 minute RELIANCE attempts, totaling 561 REJECTED and 51 INVALID. No candidate
qualifies. The [final measured review](../research/nse_equity_closeout_20261018.md)
contains cost attribution, the 111-common-date diagnostic and evidence links.

## Observation and PAPER are different

Run a bounded public observer without a database or account:

```bash
python -m helios.equities.service --run-id unique_observation_id \
  --calendar data/equities/nifty50_minutes/20261017_public_round1/nse_holidays_raw.json \
  --seconds 90
```

For the optional container, create the ignored output directory and set a
unique ID. This Compose project is separate from the existing PostgreSQL service:

```bash
mkdir -p reports_out/equity_observer
NSE_OBSERVER_RUN_ID=unique_observation_id NSE_OBSERVER_SECONDS=86400 \
  docker compose -f infra/docker-compose.equity-observer.yml up -d --build
```

The container runs as a non-root user, with read-only application/calendar and
no credentials. Preserve session artifacts before any manual cleanup. A restart
is a separate run. Normal market-closed periods produce IDLE heartbeats, never
invented prices. A heartbeat gap invalidates continuous-uptime evidence. A
90-second smoke is not a 24-hour trial. Even verified observer uptime cannot
close the PAPER deployment requirement.

The separate `python -m helios.equities.paper_runner` entry point is bounded
integration-only PAPER, with required `--run-id` and `--calendar`. It refuses
dirty source, closed sessions and missing registered NSE instrument metadata.
It uses actual provider timestamps and the existing durable risk trip/store;
quotes that precede an intent cannot fill it. Do not seed guessed tick sizes
or relabel a rejected formula as promoted merely to make it start.
`scripts/seed_nse_paper_instrument.py` retained a public Kite NSE instrument
response and registered the exact RELIANCE benchmark: lot size 1 and tick size
INR 0.1 as collected on 2026-10-18. Its audit/source proof is
[nse_public_instrument_20261018.json](../research/nse_public_instrument_20261018.json).
Dump prices are not live quotes. This current metadata does not verify historical
tick rules, adjustments or costs. A rolled-back synthetic PostgreSQL test
confirmed INR whole-share PAPER checkpoints. Public feed timeliness and a real
market-hours smoke remain operational acceptance work.

## Limits that remain

The [follow-up reference audit](../research/nse_assumption_validation_summary_20261018.md)
found concrete historical-membership, price-unit and session issues. Its findings
supersede treating those assumptions as merely unchecked. See the
[audit guide](NSE_ASSUMPTION_VALIDATION.md) for reproduction, preserved evidence
and the required new-snapshot work. Existing datasets, archived research and
promotion gates remain unchanged.

Historical Nifty membership, adjustment/corporate-action continuity, special
sessions and a causal missing-feed/liquidation policy need separate evidence.
The 15+5 bps-per-side scenario is unchanged and unverified against dated broker
invoices, taxes, rounding and observed spreads. G7 blocks promotion regardless
of a candidate's numerical score. Keep TEST sealed. Record the seven-day PAPER
trial and same-date comparison only after they actually occur.
