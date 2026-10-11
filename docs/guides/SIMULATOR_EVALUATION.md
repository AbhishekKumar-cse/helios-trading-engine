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
