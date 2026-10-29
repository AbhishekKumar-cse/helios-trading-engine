# HELIOS workstation design QA — 2026-10-29 IST

**Final findings:** no remaining actionable P0/P1/P2 findings in the tested flow.
This is an adaptation of the reviewed Alpha Harness workstation to the existing
HELIOS Streamlit application. It preserves HELIOS content, execution and research
boundaries. It is not a pixel-identical copy of BRAIN account screens.

## Source and rendered evidence

Evidence root:
`C:/Users/bit/.codex/visualizations/2026/10/15/01a13e01-c21b-7e32-82de-beb2b9a1acee/`

- Source visual truth: `alpha_harness_review_20261029/01-dashboard.png` and
  `05-template-field-binding.png`, captured from the user-authorized Alpha Harness.
- Rendered implementation: `helios_workstation_20261029/qa/10-dashboard-final.png`
  at <http://localhost:8501/?page=dashboard>.
- Full-view comparison: `helios_workstation_20261029/qa/11-full-comparison.png`.
  Source and implementation were placed together in this single comparison image,
  opened and reviewed. The 2560×744 comparison contains two unscaled 1280×720
  captures plus a 24-pixel QA label strip. The model viewer displayed a resized
  2048×595 copy; the original comparison remains saved.
- Focused comparison: `helios_workstation_20261029/qa/12-focused-comparison.png`.
  Two unscaled 500×305 crops of the heading/metrics/task surfaces, plus labels,
  were reviewed together at 1000×330. Native dashboard images were also opened.
- Final task view: `helios_workstation_20261029/qa/13-task-final.png`.
- Explicit research-status view: `helios_workstation_20261029/qa/14-research-checks.png`.
- Post-fix portfolio evidence: `helios_workstation_20261029/qa/15-portfolio-final.png`.
- Narrow-layout evidence: `08-mobile-dashboard-final.png` and
  `09-mobile-navigation.png` in the same QA folder.

Desktop CSS viewport and screenshot dimensions: **1280×720**, unchanged from the
source captures. No density conversion or image stretching. Narrow viewport:
**390×844**, screenshot at the same pixel dimensions, restored to desktop after QA.
Document/body widths were both 390 pixels; no page-level horizontal overflow.
Wide data tables retain their own horizontal scrolling.

State differences are intentional: source dashboard had a running remote BRAIN
job and account quotas; HELIOS dashboard has one completed local development job
and no running work. No source quota, identity or simulated activity was copied.
The template reference has a variable drawer open; HELIOS exposes finite field
bindings inline. Core visual comparison uses settled dashboard states.

## Comparison history and resolved findings

1. **[P1] Native header covered the breadcrumb / mode strip.** Initial evidence:
   `01-dashboard-before.png`. Fixed header minimum height and toolbar positioning.
   Post-fix `10-dashboard-final.png` shows the complete strip and reachable menu.
2. **[P2] Sidebar density hid Paper monitor below the desktop fold.** Reduced
   sidebar header, caption and button spacing; aligned button inner content left.
   `10-dashboard-final.png` shows all ten routes and the research guide at 720px.
   `09-mobile-navigation.png` confirms the narrow overlay remains operable.
3. **[P1] Returning to Template Lab cleared the expression.** Live navigation
   exposed Streamlit widget cleanup. Added a separate retained draft and a
   navigation regression test. Four workstation UI tests pass, including leaving
   and returning with the edited expression intact. Field-to-lab binding was
   verified with the real hourly dataset before the smoke test.
4. **[P2] Variable description rendered as accidental math.** Put `$field` and
   `$lookback` inside inline code. Live accessibility text now retains both names.
5. **[P2] Task controls retained the initial queue state.** Moved execution controls
   into the live fragment; `13-task-final.png` shows Start queued jobs disabled
   when queued/running counts are zero. The one-row task table now sizes to its
   rows rather than consuming a fixed empty 260px region.
6. **[P2] Equity changes were visually flattened by a zero-based axis; single-day
   portfolio data produced no visible line.** Added actual-value axes, point marks,
   clear INR labels and tooltips. The task chart now spans 100000–100120 INR for
   the observed session. Portfolio comparison uses visible points for one session.
   Daily financial values display two decimals; undefined Sharpe is labelled.
   Original results and raw receipts are unchanged.

## Required fidelity surfaces

- **Fonts / typography:** retained Streamlit's available sans-serif and system
  monospace rather than adding network font dependencies. Compact 22px page titles,
  12–13px controls, muted captions and tabular monospace metrics provide the reviewed
  hierarchy. Exact source font metrics differ intentionally. No blocked labels or
  overlapping text in tested desktop/narrow layouts. The long Sharpe metric label
  truncates with its native tooltip; its value and meaning remain accessible.
- **Spacing / layout:** 246px grouped sidebar, small radii, thin borders, four metric
  columns and a full-width work panel follow the reference composition. HELIOS adds
  useful entry actions instead of remote-account controls. Narrow metric columns
  stack; the sidebar becomes an accessible overlay. Task details remain scrollable.
- **Colors / tokens:** canvas #010102, panel #0f1011 / #141516, hairline #23252a,
  light foreground and #828fff accent follow the reviewed source palette. Semantic
  notices use native Streamlit states. Active navigation is visible without relying
  on color alone. Purple and amber distinguish the two measured cost scenarios.
- **Image / asset quality:** the target is a text/table/control workstation with no
  required photo or illustration. Existing native Material outline icons are used
  consistently; no emoji, custom SVG asset substitutes or invented avatars. The
  HELIOS wordmark is real text. Source personal/account branding is not reproduced.
- **Copy / content:** counts come from retained metadata and the real registry.
  The UI distinguishes completed development replay, measured costs, required
  certification and unassessed formal eligibility. Window units, cost assumptions
  and limits are visible before submission. No BRAIN quotas or eligible results
  are invented. Source-specific remote labels are replaced with HELIOS actions.

## Functional and accessibility verification

- Data Explorer → hourly collection → observed close field → Template Lab binding.
- One company, one lookback, one retained session, explicit hypothesis and review.
- Run now → durable local worker → COMPLETED → independent normal/doubled accounts.
- Readable task progress, disabled empty-queue control, formula and frozen scope.
- Research checks, account performance and portfolio navigation.
- Mobile sidebar expand/collapse, all routes reachable, no page overflow; viewport
  reset after inspection. Native semantic labels and keyboard controls are retained.
- Source and result integrity: 4 account artifacts and 184 archived source hashes
  verified; seven actual hourly bars, two fill legs per scenario, terminal flat.
- Registry remains at 667 attempts. No registry writes, TEST accesses or real orders.
- Final regression suite: **66 passed**. Ruff check and format check: **19 files**.
  Mypy: **14 source files**, no issues.
- Console inspected. Earlier health errors correspond to deliberate development
  server restarts; earlier chart warnings came from the replaced default charts.
  Fresh final-dashboard session logs contained zero warnings or errors. No
  unresolved app exception is visible in the final flow.
- All 266 pre-existing dirty/untracked paths verified byte-for-byte preserved.

## Accepted differences and remaining limits

This redesign retains Streamlit instead of replacing the project with Alpha
Harness's React/Tauri stack. It adds a real local development queue, not a remote
BRAIN integration. Daily/fundamental collection metadata remains browsable, while
executable templates currently use screened NSE minute/hourly OHLCV. Session bar
lookbacks do not imply 520-day research support. Unseen validation and alpha
promotion remain separate research work; the successful smoke test is not evidence
of an eligible alpha. Correlation is unavailable below 20 matched sessions.

**Follow-up polish [P3]:** exact source typography and denser table customization
can be revisited without changing the tested workflow. No P3-only iteration blocks
this handoff. Automated screen-reader certification and every historical report
layout are outside the tested scope.

**Implementation checklist:** resolved header/spacing/draft/variable/control/chart
findings; captured desktop and narrow evidence; verified a real retained-data job;
preserved lineage and unrelated work; documented local startup. No commit or push.

final result: passed
