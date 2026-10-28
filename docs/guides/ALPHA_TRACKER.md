# Alpha tracker

Open the local lab at `http://localhost:8501/?page=tracker`, or choose **Alpha
tracker** in the sidebar. The sortable sheet maps each supported alpha to its
dataset, stock scope, time period, whole/fractional units, normal/doubled-cost
return, Sharpe, trade count, performance label, original study screen and formal
eligibility. Search alpha/stock/dataset, filter the dataset or outcome, and inspect
the evidence path, hashes, blockers and next step beneath the table.

**Performance and eligibility are separate.** A positive BSE lead stays visible
even though the older portfolio experiment failed its extra screen. A basket
account that selected only BSE is still labelled basket selection; it is not
silently renamed as a preregistered stock-only experiment. The new BSE-only row is
explicitly historical implementation parity, with post-hoc stock selection. Its
future row has missing return/Sharpe/trade-count values, never invented zero
performance. Invalid accounts have no ranking. Unverified/incomplete supported
sources produce visible notices; no stale positive measurement is substituted.

The daily importer covers the official daily ADR020-025 studies, the ADR026
BSE stock-only candidate, ADR027 RELIANCE compression-breakout and ADR028
ICICIBANK pressure-recovery research. The stock-study adapters require exact
definition/instrument identity, both unit conventions and an independent12-account
audit. They do not reinterpret a basket contribution as standalone performance.
The tracker also joins every registered definition/version to its individual
results and exact data snapshot in one read-only repeatable-read transaction.
It includes crypto and NSE minute/hourly attempts, with a definition-only row
where a registered alpha has never been evaluated. On October28 this contributes
667 attempts and one draft, alongside22 audited daily rows:690 records total.
These are attempts/accounts, not690 independent alphas or independent tests.

Filter by market, frequency, evidence source, dataset and status. The evaluated
instrument comes from the run's validity/protocol evidence, rather than treating
all constituents of its input snapshot as evaluated stocks. Each attempt retains
its split, alpha version, expression, run ID and status. Registry metrics require
the original evaluation artifact's SHA-256 and snapshot/status identity to match.
Changed/missing artifacts remain visible with performance withheld. INVALID rows
keep null metrics; annual returns are never presented as total account returns.
Normal/doubled returns come from recorded cost points only. For registry records,
the Trades column counts recorded fill legs; daily studies retain their original
trade convention. Units and accounting must be checked before comparing rows.

The sheet does not claim a complete history of unregistered exploratory formats.
Those need verified adapters, rather than guessed metrics. Interactive sandbox
runs do not enter the research tracker. No rows are promoted, models fitted or
orders placed by this page. A positive score alone never establishes eligibility.

`local_state/alpha_tracker.csv` is the local derived snapshot, explicitly excluded
by `.gitignore` along with temporary replacement files. Refresh imports verified
source snapshots and atomically replaces the CSV; original evidence is unchanged.
The page is read-only for authoritative metrics. Manual changes to the generated
CSV are replaced on refresh. Download it from the page to open in spreadsheet
software. It is a local file, not a connected Google Sheet.

Refresh runs on the first tracker visit and on **Refresh from verified evidence**.
After a supported research run, update the inventory with the documented WSL Python:

```text
PYTHONPATH=research /home/abhi/.venvs/helios-runtime-312/bin/python scripts/refresh_alpha_tracker.py
```

Then refresh the page snapshot to see it. The dashboard does not start background
collection or repeatedly run research.

## BSE-only scope

ADR026 fixes BSE Ltd. on NSE, `bse_body60_v1`, the unchanged 60-session mean minus
one-SE minus exact cost hurdle. Keep10% of INR100,000 compounded capital, prior-known
opening limit/quantity rules and both normal/doubled costs. Historical parity
verifies every filled quantity, fee, net cash flow and daily cash balance against
the independently audited ADR023 accounts. It is not a new unseen result.

The separate future-only plan starts no earlier than October26,2026:60 newly
observed regular sessions for warm-up and the following60 for measurement. It
uses no original reserved TEST prices. Verified calendars, raw receipts, timely
availability and instrument continuity are prerequisites. Unknown2027 calendars
cannot be guessed; missing or stale expected observations block acceptance.
Same-stock always-participating and frozen participation-matched controls are
specified before forward observations; fractional comparisons are also required.

**The forward collector is not running and no future performance exists.** This
change freezes the candidate and evidence plan; it does not create a background
collector, schedule, PAPER session or an automatic promotion. Completing genuine
forward confirmation requires the future observations and validated collection/
evaluation path. Accepted eligibility gates, source/execution certification and
daily-cadence decisions remain unchanged.
