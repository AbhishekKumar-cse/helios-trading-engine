# Carryover from fifth semester

Review date: 2026-10-18. The new market scope is NSE cash equities using public
sources; BSE-specific ingestion has not been implemented. Original crypto
research remains intact. This list records incomplete requirements; it does
not waive the fifth-semester exit criteria.

The [public reference audit](../docs/research/nse_assumption_validation_summary_20261018.md)
has now measured the source issues: 321,060 known pre-inclusion minutes, seven
stocks with sampled adjusted-price scales, omitted Budget sessions and a short
Muhurat cohort in TRAIN. Public event and tariff evidence is retained. This
closes the diagnostic audit. Its follow-up now has a separate historical-member
snapshot: 6,909,518 real minute bars across 57 companies, with 5,069,595 screened bars
from 41 companies. ADR010 implements the special-session calendar and opt-in
side/order/day-aware simulated charges. Known uncertain units remain quarantined;
retrospective membership/completeness does not establish tradable PIT availability.
See [rebuild guide](../docs/guides/NSE_REBUILD.md) and data verification receipt
`docs/research/nse_rebuild_data_checks_20261018.json`.
The [new verified round](../docs/research/nse_rebuild_closeout_20261018.md) completed
with two REJECTED quantitative baselines and one INVALID constant ML alpha.
Its 43,665 fills and 228 candidate/session replays reconcile. No candidate is
eligible for promotion; all previous artifacts and TEST counters remain intact.

| ID | Linked step | Remaining evidence | Closure condition |
|---|---|---|---|
| NSE-DATA-01 | 5B, 5G, 5I | Certified raw share units, corporate actions and causal ticker/membership availability | Retrospective member reconstruction exists; excluded unit histories need independent raw observations and a tradable PIT policy |
| NSE-DATA-02 | 5B, 5J | Causal handling of live gaps | Historical full/short calendar is implemented; still need outage/liquidation policy without ex-post session selection |
| NSE-COST-01 | 5F, 157 | Historical brokerage acceptance, spread and impact evidence | Reference statutory estimates/order caps/day settlements implemented; historical account tariff and observed liquidity remain unverified |
| NSE-LIVE-01 | 160, 166 | Real market-hours public-feed PAPER acceptance | Current RELIANCE metadata is registered from a retained public dump; still need a clean-source bounded PAPER artifact with genuine timestamps, durable checkpoints, kill and cancellation; reject stale/delayed data |
| NSE-RESEARCH-01 | 5I | Broader minute execution cohort and performance budget | Original minute model pools 50 stocks; rebuilt model uses 41 screened historical members. Execution benchmark remains RELIANCE; expand a preregistered cohort before all-company minute claims |
| NSE-LIVE-02 | 166 | Always-on PAPER deployment | Measured unattended 24 hours on a host that stays awake; OBSERVE heartbeats alone do not qualify |
| NSE-SELECT-01 | 139, 163 | Eligible equity candidate and preregistered governed TEST adapter | Validated source assumptions, accepted gates and atomic access policy; never force a winner or open TEST for a rejected candidate |
| NSE-LIVE-03 | 167 | Promoted-candidate seven-day trial | Eligible promotion, explicit calendar, restart/reconciliation and seven actual days of PAPER records |
| NSE-COMPARE-01 | 170 | PAPER versus backtest on the same observed dates | Compare actual retained observations and explain divergence after the trial |
| NSE-DEMO-01 | 174 | Full final demo including live NSE PAPER and kill switch | Authentic recorded market-hours demonstration; a research-only preview is insufficient |
| TEAM-01 | 010, 022 | Team invitations, clones and other laptops | Teammate evidence; do not infer from this workstation |
| NEXT-LOB-01 | 168 optional, 6A-06 | Tick/order-book data access and recorder | Source/rights/scope decision before any equity microstructure claim |

The report, SRS addendum, public-minute implementation and exact archived replay
are current deliverables. Fresh local checks on uncommitted code are not remote
CI for a new commit. The final CI evidence must follow any later authorized push.
No profitable alpha, real-capital execution, 24-hour PAPER soak or seven-day
equity trial is claimed. A supervisor may approve a revised academic scope, but
no such approval is recorded here.
