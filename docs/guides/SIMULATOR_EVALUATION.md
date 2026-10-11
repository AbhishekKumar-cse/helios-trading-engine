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
