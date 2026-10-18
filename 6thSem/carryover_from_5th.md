# Carryover from fifth semester

Review date: 2026-10-18. The new market scope is NSE cash equities using public
sources; BSE-specific ingestion has not been implemented. Original crypto
research remains intact. This list records incomplete requirements; it does
not waive the fifth-semester exit criteria.

| ID | Linked step | Remaining evidence | Closure condition |
|---|---|---|---|
| NSE-DATA-01 | 5B, 5G, 5I | Historical membership, corporate actions and ticker continuity | Independent dated source and tested point-in-time universe |
| NSE-DATA-02 | 5B, 5J | Special sessions and causal handling of live gaps | Versioned exchange-calendar and outage/liquidation policy; no ex-post availability selection for tradable claims |
| NSE-COST-01 | 5F, 157 | Dated brokerage/tax/rounding, spread and impact evidence | Audited effective-date cost schedule and observed liquidity checks; preserve old proxy results |
| NSE-LIVE-01 | 160, 166 | Real market-hours public-feed PAPER acceptance | Current RELIANCE metadata is registered from a retained public dump; still need a clean-source bounded PAPER artifact with genuine timestamps, durable checkpoints, kill and cancellation; reject stale/delayed data |
| NSE-RESEARCH-01 | 5I | Broader minute execution cohort and performance budget | First minute model pools 50 stocks but execution tests use RELIANCE; expand the preregistered execution cohort explicitly before claiming all-company minute results |
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
