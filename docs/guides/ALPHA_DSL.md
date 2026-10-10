# Alpha DSL parser, safety and evaluator (steps 086, 088–092)

```python
from helios.alpha.parser import parse_expression

tree = parse_expression("zscore(ret_1, 24) * -1")
```

`parse_expression` returns a validated `ast.Expression`. It uses `ast.parse` in
expression mode and checks every node against an explicit whitelist. It does not
execute the expression, read market data, open a database or load models. There is
no `eval` or executable compilation of the returned tree. Subsequent evaluators
must interpret DSL nodes directly rather than delegate execution to Python.

Supported syntax is finite real numeric constants, lowercase ASCII names,
parentheses, binary `+ - * /`, unary `+ -`, and these direct positional calls:

| Function | Arguments |
|---|---|
| `zscore`, `ts_mean`, `ts_std`, `rank_ts` | series, window |
| `lag` | series, periods |
| `sign` | series |
| `clip` | series, lower, upper |
| `where` | condition, if_true, if_false |
| `cs_rank`, `cs_demean` | series; requires a universe context |

Names may contain digits and underscores after their first lowercase letter;
private/dunder names are rejected. The whitelist and function arities are exposed
as immutable collections. Booleans, strings, complex values and non-finite numeric
literals are rejected. So are statements, attribute/subscript access, containers,
comprehensions, lambdas, assignments, comparisons, boolean/bitwise operators,
exponentiation, arbitrary calls, keyword arguments and argument unpacking.
The current `where` grammar takes a numeric condition expression; Python comparison
syntax is not part of this whitelist. Cross-sectional calls use the universe API below.

Malformed, disallowed or excessive expressions raise `DSLParseError`. Bounds are
4,096 source characters, 256 AST nodes and an AST depth of 32. Validation walks the
tree iteratively, including every nested argument. Numeric literals must be finite
when represented as float64; an oversized integer cannot bypass that check.

Step 086 validates **structure only**. Names are not yet resolved against a feature
set or parameter mapping. In particular, the plan's `ret_1` is a syntactically valid
name, not a newly introduced alias for the registered `log_return_1`. Use actual
registered feature names in runnable definitions. A successful parse does not mean
a feature exists, a window is valid, or a lag is causal: `lag(x, -1)` passes this
structural stage but is rejected by the function evaluator before a result is
returned. Steps 088–089 implement arithmetic/functions with the controls needed
to evaluate safely; step 090 adds a data-independent semantic preflight and suite.
The parser does not generate alpha values, simulation results or performance observations.

## Semantic preflight (step 090)

```python
from helios.alpha.safety import validate_expression

tree = validate_expression(
    "clip(zscore(lag(log_return_1, k), window), -1, 1)",
    feature_names=("log_return_1",),
    params={"k": 1, "window": 24},
    interval="1h",
)
```

This checks the parser whitelist and every feature/parameter binding without
reading a `FeatureFrame`, allocating series or computing statistics. It checks
both `where` branches, even under a constant condition, and does not exempt
names multiplied by zero or hidden inside a window longer than available history.
Lag must be an integer >= 1; mean/rank windows >= 1, std/zscore windows >= 2.
Controls must be finite scalar constants/parameters or their arithmetic, below
2**63 for counts. Feature-derived windows/bounds, negative/zero/fractional lag,
control zero division/overflow, reversed clip bounds and missing intervals fail.

Unknown/full-sample functions (`mean`, `std`, `sum`, `rank`, `quantile`, `pca`,
etc.) and attributes such as `x.mean()` are rejected structurally, with no
fallback to pandas/Python execution. Trailing functions require an explicit
finite window; a window exceeding history is valid but yields unavailable output,
never shortened into an implicit full-sample reducer. Full-sample statistics
cannot be used as expression controls. Callers remain responsible for parameters
being chosen without held-out-data leakage; static validation cannot establish
how externally supplied values were obtained.

`evaluate_expression` performs the same semantic pass before computing any branch.
It reparses source; it never accepts the returned tree as executable input.
`DSLParseError` covers syntax/function whitelist failures; `DSLEvaluationError`
covers bindings/control failures (the existing evaluator import remains supported).
Standalone preflight trusts the declared feature schema; successful validation
does not certify input feature causality, mask/data integrity or profitability.

To parse a loaded step-085 QUANT definition:

```python
from helios.alpha.definition import load_alpha_definition
from helios.alpha.parser import parse_expression

idea = load_alpha_definition("configs/alphas/examples/btc_hourly_momentum.yaml")
if idea.expression is not None:
    tree = parse_expression(idea.expression)
```

YAML loading and registration still validate definition metadata only. This parser
is a separate explicit stage; it neither changes registered definitions nor edits
their immutable version history.

## Pointwise arithmetic (step 088)

Given a `FeatureFrame` named `features` from the existing feature runner:

```python
from helios.alpha.evaluator import evaluate_expression

alpha = evaluate_expression(
    "log_return_1 - scale * close_over_mean_12",
    features,
    params={"scale": 0.5},
)
usable_values = alpha.values.loc[alpha.available]
```

The evaluator parses source through the whitelist itself and interprets numeric
constants, names, unary signs and `+ - * /` directly with NumPy. It accepts source
text, not a caller-supplied/mutated AST. There is no Python `eval` or executable
compilation. A loaded definition's arithmetic expression and `params` can be
passed in the same way. Step 089 also evaluates the eight whitelisted functions
described below.

The returned `AlphaSeries` carries the input coin symbol, copied UTC-microsecond
timestamps, float64 `values` and boolean `available`. Row indexes and order are
preserved; gaps are not filled, rows are not sorted/joined, and no additional
timestamps are generated. Input tables must have matching unique indexes/columns
and chronological unique integer timestamps. Multi-coin frames must be separated
before this API, as with the existing feature runner.

Names bind to actual columns in the supplied feature frame or finite numeric
scalar parameters. Missing names raise an error; plan shorthand such as `ret_1`
is not silently aliased. Parameters cannot shadow feature/function names, and
boolean, nonnumeric, NaN/Infinity or oversized values are refused. All supplied
parameters must be numeric scalars for this evaluator, including unused ones;
the step-085 definition model's broader JSON parameter support is unchanged.
Referenced feature columns must be real numeric values with non-null boolean masks.

Every binary operation intersects its two operand masks and checks the resulting
value is finite. False input masks override even finite source values. NaN/Infinity
inputs, arithmetic overflow and division by zero (including signed zero and 0/0)
produce NaN with false availability. They never become zero-filled observations.
`0 * unavailable_feature` and `feature - feature` remain unavailable where that
feature is unavailable. Zero itself is valid. Constants/parameters broadcast only
to existing rows, and unused feature masks do not restrict their availability.

Arithmetic is pointwise and adds no new warm-up/history requirements; feature
warm-up and gap masks already supplied by the runner flow through unchanged or
combine by intersection. Changing/truncating future inputs cannot rewrite earlier
outputs. Inputs are not mutated and output series do not share their mutable data.

These are **raw**, unbounded alpha values: no automatic normalization, final clipping,
strategy selection, costs, P&L or performance evaluation is performed. Use the step-092
definition evaluation API below for final bounded output. Step 088's tests use
synthetic, hand-calculated data and do not claim
market observations or predictive value.

## DSL functions (step 089)

```python
alpha = evaluate_expression(
    "clip(-zscore(log_return_1, window), -1, 1)",
    features,
    params={"window": 168},
    interval="1h",
)
```

Rolling functions and `lag` require an explicit supported candle `interval`.
The evaluator never infers an interval from timestamp differences: missing bars
could make an hourly series appear to have a longer decision interval. Pointwise
arithmetic, `sign`, `clip` and `where` keep working without this argument.

| Function | Value and availability contract |
|---|---|
| `ts_mean(x, w)` | Trailing mean including the current row; w >= 1. |
| `ts_std(x, w)` | Trailing sample standard deviation (ddof=1); w >= 2. Constant windows return 0. |
| `zscore(x, w)` | (current value − trailing mean) / trailing sample std; w >= 2. Zero variance is unavailable. Uses the existing feature helper. |
| `rank_ts(x, w)` | Current value's ascending average-tie rank / w; w >= 1. Constant windows rank (w+1)/(2w). Uses the existing feature helper. |
| `lag(x, k)` | Value/mask from k earlier rows; k >= 1, with k+1 consecutive timestamps. Current/intermediate x masks do not affect an otherwise valid lagged endpoint. |
| `sign(x)` | −1, 0 or +1, retaining the operand mask. |
| `clip(x, lower, upper)` | Explicit bounds with lower <= upper, retaining the operand mask. This is not automatic final bounding. |
| `where(condition, yes, no)` | Finite nonzero condition selects yes, zero selects no. Requires a usable condition and only the selected branch's mask. |

Rolling windows require **all w operand values available and finite**, plus w
consecutive timestamps on the specified UTC candle grid. Warm-up, missing inputs,
gaps or off-grid timestamps remain NaN/false; there is no filling. Nested functions
carry their own warm-up/masks into outer windows. A lag is unavailable until k
earlier rows exist and elapsed timestamps are contiguous; it cannot bridge a gap
by treating the preceding stored row as the preceding period. A requested history
longer than the supplied frame produces wholly unavailable output without padding.

Window/lag counts and clip bounds use finite scalar literals, numeric parameters
or arithmetic composed from them. Feature-dependent controls and function calls
inside controls are refused. Counts must be integer-valued, at least the function's
minimum and below 2**63; an integral scalar such as 3.0 is accepted as three bars.
Zero/negative/fractional lags and inappropriate windows are rejected immediately.

`where` uses numeric conditions because Python comparisons remain outside the
parser whitelist. Negative values are nonzero/true. An unknown condition stays
unavailable, even if both branches happen to have the same value. Branch expressions
are both validated/evaluated; unknown names and invalid controls are errors even
in an unselected branch. However, unavailable or non-finite **values** in an
unselected branch do not poison a valid selected value.

All eight functions are tested with hand calculations and future changes/truncation.
The existing QUANT YAML examples now evaluate against a compatible feature frame.
No alias is introduced for ret_1/ret_24, and no definitions/results are registered
by evaluation. Step 090 now checks these controls before any series computation.
Parameter counting (093) and baseline registration (094) remain pending.

## Cross-sectional functions (step 091)

Given a mapping of declared symbols to their existing `FeatureFrame` objects:

```python
from helios.alpha.cross_sectional import evaluate_universe_expression
from helios.common.db import get_engine
from helios.data.universe import listing_dates

with get_engine().connect() as connection:
    catalog = listing_dates(connection)

alphas = evaluate_universe_expression(
    "cs_demean(cs_rank(log_return_24))",
    frames_by_symbol,
    listing_dates=catalog,
    interval="1h",
)
```

The symbol mapping declares the universe up front; use the planned BTCUSDT,
ETHUSDT, SOLUSDT, BNBUSDT and XRPUSDT frames for the five-coin research universe.
Supply a first-available `date` for every declared symbol, from the existing catalog
or a recorded historical snapshot. Extra catalog symbols do not expand the mapping.
The catalog includes later-inactive instruments; callers must retain historical
members rather than filter them by today's active flag. Dates represent earliest
observed data, not a claim about exchange listing history.

Membership starts at inclusive UTC midnight on that date. All pre-membership
output is NaN/false, including constants, and pre-membership history cannot enter
rolling windows. Empty frames can represent members without data in the supplied
period. An empty universe is rejected. The evaluator performs no database writes.

Each cross-sectional call aligns operands by exact UTC-microsecond timestamp,
independently of their source row indexes. Every listed member must have a finite,
available operand at that timestamp. A missing row, false mask, non-finite value
or shifted timestamp makes the entire cross-section unavailable. Unlisted members
are excluded. No smaller universe is silently substituted, and no nearest-time
matching, filling or fabricated output rows occurs.

`cs_rank(x)` returns ascending average-tie rank divided by the eligible count.
Five equal operands therefore rank 0.6 each. `cs_demean(x)` subtracts the equal-weight
mean of eligible same-time operands. One eligible member ranks 1 and demeans to 0;
the minimum-five rule for cross-sectional IC metrics is separate from these transforms.
Ordinary floating-point rounding applies, and non-finite results remain unavailable.

Time-series and cross-sectional functions can be nested. For example,
`lag(cs_rank(x), 1)` lags earlier ranks while `cs_rank(lag(x, 1))` ranks lagged
operands using membership at the current timestamp. Rolling/lag calls still require
an explicit interval and contiguous available history. Each returned `AlphaSeries`
preserves its coin's existing timestamps, row indexes and order; inputs are copied
or read without mutation. This low-level expression API returns raw values; the
definition evaluation API below applies final bounds after all cross operations.

The single-coin `evaluate_expression` rejects cross-sectional calls anywhere in the
formula, including unselected branches. Standalone semantic preflight accepts them
only with `cross_sectional=True`; that flag declares a context, but does not verify
an actual universe or market data. The universe evaluator validates all frames,
bindings and controls before computation. Tests use synthetic hand calculations,
listing/missing-data cases and future perturbations, without claiming market results.

## Final output and scale convention (step 092)

```python
from helios.alpha.definition import load_alpha_definition
from helios.alpha.output import evaluate_definition

idea = load_alpha_definition("configs/alphas/examples/btc_hourly_momentum.yaml")
alpha = evaluate_definition(idea, features, interval="1h")
assert alpha.output.convention == "clip_unit_v1"
```

`evaluate_definition` and `evaluate_universe_definition` complete the full formula
through the raw evaluators, then clip finite available final values to [-1, 1].
The universe variant takes the same symbol mapping and `listing_dates` as above.
Intermediate arithmetic, rolling and cross-sectional values are never automatically
clipped: clipping before subtraction or demeaning would change the formula.
`bound_alpha(raw)` also exposes the finalization boundary for separately computed
series. It checks row alignment, numeric values and masks, preserves timestamps,
copies output data, and returns a `BoundedAlphaSeries` carrying its convention.
NaN, infinity and false masks remain NaN/false; infinity never becomes a saturated
position. Empty historical members stay empty, and warm-up masks stay unavailable.

New definitions carry `output` metadata (defaults shown):

```yaml
output:
  convention: clip_unit_v1
  lower: -1
  upper: 1
  position_scale: 1.0
```

Bounds and convention are fixed in this version. `position_scale` must be finite,
positive and numeric; it is reserved for step-095 position mapping
`clip(alpha / position_scale, -1, 1)`. Finalization stores it without dividing by it,
avoiding double scaling later. It is separate from an expression parameter named
`scale`. Changes to this metadata affect the definition fingerprint and require a
new registered version. The adapter stores it in insert-only `spec_json.output`,
without migrating or editing old database rows. YAMLs omitting it receive explicit
defaults when loaded; old stored rows do not acquire metadata silently.

Model references require a separate inference pipeline and are rejected by these
expression entry points. No model is loaded, simulator run or result registered.
