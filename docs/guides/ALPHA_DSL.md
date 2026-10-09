# Alpha DSL parser (step 086)

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
structural stage but must be rejected by step 090 before evaluation. Steps 088–089
implement arithmetic/functions; step 090 adds semantic safety checks. The parser
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
