# Fifth-semester completion after the NSE extension

Assessment: 2026-10-17. Checked the actual implementation, measured first equity
round, [semester plan](../../5thSem/5thSem_Plan.md), and
[sequential checklist](../../5thSem/5thSem_Sequential_Steps.md).
This is a status assessment, not an amendment to the accepted exit criteria or
an instruction to mark historical crypto steps complete for equities.

## Already demonstrated on equities

- Frozen current Nifty 50 roster and downloaded daily/hourly/recent-minute
  Yahoo-distributed NSE-listed prices, with hashes and quality evidence.
- Daily/hourly prediction pilot; new TRAIN-only hourly classifier with disjoint
  TRAIN-tail expected-return calibration.
- Shared hourly evaluator, formula DSL, strategy/risk/OMS/simulated execution,
  whole-share INR ledger, metrics/Fitness/gates, registry and reports.
- All 150 preregistered attempts completed: three candidate definitions across
  50 companies. These are **three hypotheses, not 150 distinct alpha ideas**.
  Both formula candidates were rejected on every company; ML stayed flat and
  was INVALID on every company. No equity candidate is eligible for promotion.
- Lab displays retained outcomes, fills, fees, coverage and equity curves.
  Existing crypto results and TEST access remain unchanged.

Evidence: [measured research and verification](nse_shared_research_20261017.md).
The implemented stock source is NSE-listed equities; a separate BSE price
collector has not been implemented. Working on both exchanges is not necessary
unless the agreed academic scope explicitly requires both.

## Equity work needed to meet the original hourly-to-minute scope

| Remaining work | Why it remains |
|---|---|
| Establish stronger equity source and execution assumptions | Official exchange calendar/special sessions, historical membership, corporate actions/ticker continuity, and appropriate brokerage/tax/slippage validation are unverified. Current complete-session selection is ex-post; a causal missing-feed policy is still needed for tradable claims. G7 deliberately blocks promotion. |
| Complete the NSE hourly research programme | The integration round tested momentum, reversal and one ML definition. The original 5G scope calls for 8–10 preregistered hypotheses, baseline comparison and a search-effort summary. Broader equity hypotheses need new preregistration, not relabelling the crypto experiments. Features requiring unavailable trade/taker-flow fields need supported alternatives with recorded definitions. |
| Acquire enough real minute history and implement the NSE minute path | Recent minute download is an ingestion sample, not adequate TRAIN/VALID history. `EquityResearchPolicy`, `EquityBacktestConfig` and the pipeline currently support hourly evaluation only. NSE minute feature/label/split/annualisation, execution and gate adapters need implementation and causality checks. |
| Run equity minute research and ML through shared gates | Repeat 5I: baselines plus 6–8 preregistered hypotheses, fixed/calibrated ML, cost sensitivity and comparable daily-aggregated hourly/minute diagnostics. Retain every failed/INVALID attempt. |
| Add governed equity selection/holdout support when justified | Current equity evaluator rejects TEST unconditionally. It has no equity final-selection/TEST workflow. Keep TEST sealed until eligible candidates and a preregistered access policy exist; record no-eligible outcomes rather than manufacturing a winner. |
| Connect an authorized live equity feed to PAPER | Current `PaperConfig`/runner remains BTCUSDT/Binance-specific. Shared INR backtest support does not supply a live NSE feed, session-aware PAPER configuration, durable restart/reconciliation or a multi-session service. |

The framework is reusable; these are market-data, policy and adapter gaps. The
existing crypto/FI-2010 implementations and results remain valid as their own
work. NSE prices cannot supply missing order-book or taker-flow observations.
Further ML integration does not guarantee profitable alpha.

## Remaining numbered closeout steps

| Steps | Evidence still needed |
|---|---|
| 166 | Always-on PAPER deployment and a measured unattended 24-hour service trial. For equities the service may idle outside market hours; 24 hours awake is an uptime check, not 24 trading hours. The existing Compose file deploys PostgreSQL/Adminer, not the PAPER worker. |
| 167, 170 | Eligible/promoted-candidate seven-day PAPER records, then a backtest over the same observed dates and a divergence report. Define session/calendar handling for NSE before starting. There is currently no promoted equity candidate; an integration-only run cannot be presented as fulfilling the promoted-alpha condition. |
| 169 | Actual rerun of a stored result from its lineage with identical numbers. Current artifact/hash/ledger reconciliation is verification, not a full rerun. The development equity source archive must be retained even after the implementation is committed. |
| 171 | Final branch-protection/property/leakage/registry review and required screenshot/evidence. Read-only GitHub API check on 2026-10-17 confirms strict required contexts `lint, types, tests` and `leakage (required)`; property tests run inside the main test job. This does not complete the checklist's screenshot/sign-off requirement. |
| 172–175 | Update SRS/spec and scope for NSE, measured semester report including negative findings, recorded demonstration, and `6thSem/carryover_from_5th.md`. The carryover file is absent at this review. |
| 168 (optional) | Order-book recorder for next-semester preparation. Original task is BTC/ETH; equity tick/order-book recording needs its own suitable source and scope decision. It is not a required fifth-semester bar-research deliverable. |

The checklist also retains unchecked **010** (team/repository onboarding) and
**022** (other members' laptop setup). Branch protection now exists, but teammate
invitation/clone evidence was not independently established by this review.
These administrative boxes should be reconciled with the team.

## Completion judgement

The equity hourly research integration is complete. The full fifth-semester
scope on NSE data is not complete: minute research, the live equity PAPER path
and sustained run, exact rerun evidence, and academic closeout remain.

Negative research is a valid measured result. It does not justify inventing a
promoted alpha, lowering recorded gates or claiming a PAPER trial occurred.
If the course accepts an honest no-eligible-candidate outcome in place of the
original promoted-alpha trial, record that scope decision and carryover with the
supervisor; no such change is assumed here.
