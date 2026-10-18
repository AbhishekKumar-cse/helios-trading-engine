# Public NSE assumption audit

The user authorized validating the equity data and trading assumptions before
further research. The read-only audit is complete; it found source and protocol
issues. Read the [measured review](../research/nse_assumption_validation_summary_20261018.md)
and its compact companion JSON. No old source, alpha result, gate or TEST policy
was changed. The audit's measured development lineage remains retained when its
implementation is later committed; the separate rebuild is described in
[NSE_REBUILD.md](NSE_REBUILD.md).

## What the audit establishes

All 900 original monthly response hashes and all 50 stock Parquets were verified.
Public NSE corporate-action requests returned 124 events across the 50 companies.
Four official index-review notices establish specific membership violations.
Forty-four official daily exchange files support 2,200 company/date comparisons.
Normal-session holidays and the reviewed Budget/Muhurat sessions have retained
official notices. The detailed comparison payload and raw reference responses
remain under ignored `reports_out/nse_validation/`.

This is retrospective evidence. An ex-date is not an announcement timestamp;
current company symbols/ISINs do not establish complete historical identity;
one daily-file sample is not proof of every minute. The audit labels missing
identity matches and possible price-scale differences without repairing them.

The existing snapshot was deliberately a current-company, normal-session study.
The audit quantifies why that scope cannot be relabelled a point-in-time Nifty
dataset or realistic whole-share execution history. The original 612 research
measurements remain retained under their original assumptions.

## Reproduction

Use the documented WSL Python environment. Commands require the original ignored
source snapshot and database used for the independent registry fingerprint check.
Choose new output paths; do not overwrite completed evidence.

```bash
export PATH=/home/abhi/.venvs/helios/bin:/home/abhi/.local/bin:/usr/bin:/bin
python scripts/collect_nse_validation.py \
  data/equities/nifty50_minutes/20261017_public_round1 \
  reports_out/nse_validation/new_reference_id
python scripts/supplement_nse_validation.py \
  reports_out/nse_validation/new_supplement_id
```

The collector retains source URLs, response status, time and hashes. Refusals are
not bypassed. It uses metadata and only January2025–June2026 daily prices, never
reserved price TEST dates. Its original pre-format source is retained beside
the completed collection as `collector_source.py`; the source hash in the
protocol must match. A new collection should similarly retain its collector:

```bash
cp scripts/collect_nse_validation.py \
  reports_out/nse_validation/new_reference_id/collector_source.py
python scripts/audit_nse_assumptions.py \
  data/equities/nifty50_minutes/20261017_public_round1 \
  reports_out/nse_validation/new_reference_id \
  reports_out/nse_validation/new_supplement_id \
  reports_out/nse_validation/new_audit_id
```

The auditor freezes its new source/facts, verifies original raw bytes, checks
corporate events/ISINs/session dates, counts known pre-inclusion rows and checks
sampled price scales. It also compares charges on the retained minute fills.
Crypto definitions/results and TEST counters are compared before and after.

The existing publication helper reviews the fixed measured counts of the
20261018 audit. It deliberately refuses a different set of measured facts;
adapt/version its prose for a future audit rather than reuse old fixed claims.

```bash
python scripts/report_nse_validation.py \
  reports_out/nse_validation/20261018_reference1/assumption_audit.json \
  docs/research/new_review_id
```

## Charge estimator boundaries

`helios.equities.charges` supports whole-share cash trades that finish flat for
every security/day. It groups partial fills by executed order for the brokerage
cap. STT uses security/day combined trade VWAP, rounded to paise; security STT is
rounded to paise and client-day STT to rupees. Other components are unrounded
estimates, not an asserted contract note. Invalid or TEST dates, nonfinite inputs,
fractional quantities and non-flat inventories are refused.

Exchange/IPFT components follow dated official circulars. Brokerage is an
explicit current public Zerodha scenario, not a verified historical account
tariff. No delivery/overnight, financing, auto-square-off or real execution is
modeled. Slippage/spreads/impact are not certified by OHLCV data.

The diagnostic does not replace `EquityResearchPolicy.fees()` or replay a new
strategy. Integrating side/order/day-aware billing into execution requires a
new accepted version and preregistered run. Never overwrite the old 15+5-bps
scenario or infer new alpha performance from a fee-only calculation.

## Verification

The new audit/charge tests and existing minute regressions pass: 22 tests.
Strict mypy passes for 133 source files; Ruff lint and formatting pass for 322
files. The [verification receipt](../research/nse_assumption_validation_checks_20261018.json)
binds the logs, runtime archives, original research lineages and published summary.
Tests include the independently published STT example, client-day
aggregation, partial-fill caps, dated exchange/IPFT consistency, non-flat/TEST
refusal, embedded daily-file date checks, path/hash/journal tampering and
nonfinite-price rejection. Actual detailed audit counts and original fingerprint
checks are retained in the evidence, not synthesized from test fixtures.

The next implementation is a new historical-membership and share-unit-aware
dataset/calendar, followed by a new execution cost policy and research round.
G7 remains blocked until the full source/execution requirements are met.
