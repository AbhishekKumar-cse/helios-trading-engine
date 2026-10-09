# Alpha DSL parser and arithmetic evaluator (steps 086, 088)

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

Names may contain digits and underscores after their first lowercase letter;
private/dunder names are rejected. The whitelist and function arities are exposed
as immutable collections. Booleans, strings, complex values and non-finite numeric
literals are rejected. So are statements, attribute/subscript access, containers,
comprehensions, lambdas, assignments, comparisons, boolean/bitwise operators,
exponentiation, arbitrary calls, keyword arguments and argument unpacking.
The current `where` grammar takes a numeric condition expression; Python comparison
syntax is not part of this whitelist. Cross-sectional functions remain step 091.

Malformed, disallowed or excessive expressions raise `DSLParseError`. Bounds are
4,096 source characters, 256 AST nodes and an AST depth of 32. Validation walks the
tree iteratively, including every nested argument. Numeric literals must be finite
when represented as float64; an oversized integer cannot bypass that check.

Step 086 validates **structure only**. Names are not yet resolved against a feature
set or parameter mapping. In particular, the plan's `ret_1` is a syntactically valid
name, not a newly introduced alias for the registered `log_return_1`. Use actual
registered feature names in runnable definitions. A successful parse does not mean
a feature exists, a window is valid, or a lag is causal: `lag(x, -1)` passes this
structural stage but must be rejected by step 090 before evaluation. Step 088 now
implements arithmetic; step 089 implements functions and step 090 adds remaining
semantic safety checks. The parser
does not generate alpha values, simulation results or performance observations.

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
passed in the same way. Function calls raise `DSLEvaluationError` until step 089,
even though the structural parser recognizes their permitted syntax.

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

These are **raw**, unbounded alpha values: no normalization, final clipping,
strategy selection, costs, P&L or evaluation is performed. Step 092 will add final
bounding. Step 088's tests use synthetic, hand-calculated data and do not claim
market observations or predictive value.
