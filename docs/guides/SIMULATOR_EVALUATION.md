# Simulator evaluation safeguards

## Alpha validity (106)

`alpha_validity(alpha, config=ValidityConfig(...))` returns an immutable VALID or
INVALID result, reason codes, counts and hashes of its settings and exact input.
Constant post-warm-up signals, insufficient return intervals, available non-finite
signals and unavailable signals after warm-up are INVALID. This is different from
a valid simulation failing selection gates (REJECTED).

Warm-up is an explicit number of leading rows supplied from the feature/alpha
requirements, never inferred by dropping rows up to the first finite value.
The first remaining row is an accounting boundary, so N rows represent N-1
return intervals. The default minimum of two intervals is the sample-variance
minimum; callers can record a stricter minimum. It is not an adequacy or promotion
threshold. Unknown values within declared warm-up are allowed; a claimed available
NaN or infinity is still invalid. A missing value after warm-up is never filled.

Malformed indexes, timestamps, value types and availability masks raise a contract
error. Validity does not inspect performance, make promotion decisions or write
registry rows. The later registered evaluator must retain INVALID attempts with
their reasons; the existing numeric-result writer is not used for invalid inputs.

## Chronological splits and TEST access (107)

`split_window(split, interval=..., horizon_periods=...)` snapshots `splits.yaml`,
converts its inclusive UTC dates to half-open microsecond bounds and checks that
the registered prediction horizon fits within the embargo. Only configured hourly
and minute families are supported; accepted dates are unchanged.

`evaluate_split(engine, ..., load_inputs=callback)` evaluates one explicit split.
It requires a registered alpha version with matching family/horizon and an open
experiment. The callback receives the immutable authorized window and may load
earlier causal feature history, but must not inspect another future split. Its
returned rows beyond the authorized end are refused. Earlier history and embargo
rows are excluded from metrics, exact timestamp alignment exposes missing alpha
as unavailable, and validity runs before performance calculations.

Declared warm-up rows are excluded before starting a fresh flat simulation.
The first remaining close is its accounting boundary: there is no position or
return carried across the embargo, and initial entry costs are charged again.
Later unknown values/gaps are not dropped. INVALID returns reasons without
diagnostics. Valid results retain separate net diagnostics and split JSON/hash.
These are reference-exposure simulations, not orders or persisted result rows.

For TEST, a registered experiment snapshot, actor and purpose are required.
The existing advisory-lock-protected access counter reserves one of two uses in
an **independent committed transaction before invoking the input callback**.
Loader failures and invalid simulations still consume the reserved use. The
third access fails before loading. TRAIN/VALID use no TEST budget. No default
all-splits evaluation exists. Loading and feature construction remain trusted
caller responsibilities; this API cannot undo a caller's earlier unauthorized
inspection of a dataset. PostgreSQL tests run reservation checks in rolled-back
fixtures; separate orchestration tests check commit-before-load ordering.

## Selection gates (108)

`gate_decisions(...)` is the pure comparison kernel. `evaluate_gates(split_result,
fitness=..., stability=..., costs=...)` checks matching source/config lineage and
returns immutable G1–G6 PASS/FAIL outcomes, measured values, thresholds, comparison
rules, reasons, exact gate JSON/hash and base simulation lineage. It rechecks actual
simulation bounds and diagnostics, verifies TEST's matching reservation and
recalculates Fitness from the recorded gate settings. Evidence from another split,
snapshot, fee assumption or configuration is refused.

Accepted defaults are strict: G1 annual net Sharpe > 1; G2 Fitness > 1;
G3 0.01 < mean turnover < 0.70; G4 VALID or TEST; G5 positive monthly fraction
> 0.5; G6 annual Sharpe at 2x assumed costs > 0. Exact boundaries fail.
Missing or undefined evidence fails closed; non-finite evidence/settings are
contract errors. A configured alternative stress multiplier uses its exact curve
point; absence of that point fails G6. G5 requires every observed month's Sharpe
to be defined, preventing omission of undefined months from improving selection.
Weekly evidence is not implemented by the monthly report, so a recorded weekly
configuration fails G5 rather than silently using months.

INVALID alpha remains INVALID with its original validity reasons; gates are marked
failed with `invalid_alpha` without treating the attempt as performance evidence.
A valid alpha failing any gate is REJECTED. All gates passing yields EVALUATED,
never automatic PROMOTED: clean lineage and registry lifecycle authorization remain
separate requirements. A recorded `require_out_of_sample=false` is visible in G4's
reason and changed config hash. No accepted configuration file is changed here.

## Noise calibration (109 / SIM-014)

`test_sim_noise.py` runs all 20 fixed signal seeds (0–19) on 20,000 independent
synthetic hourly return intervals from a separate fixed market generator. Signals
pass through bounding, the actual lagged-position kernel, costs and metrics.
Nothing is fitted, selected or omitted by score; no database or market data is
needed, so the control runs in CI.

The zero-cost null requires the mean annual Sharpe to be within three standard
errors of zero, both from the a priori null scaling sqrt(8760/(20000*20)) and
the observed variation across seeds. The measured synthetic mean is 0.05430368,
null SE 0.14798649 and observed SE 0.14210222. Individual noise seeds need not
have zero Sharpe. A companion 20-seed test applies accepted fee/slippage settings
and verifies negative average net returns and actual cost subtraction. Zero
expected gross edge does not imply zero net edge after costs. These are simulator
calibration results, not evidence about a real alpha or market profitability.

CI has an explicit noise-control step; the main test invocation excludes this
file to avoid running the same controls twice in that workflow.
