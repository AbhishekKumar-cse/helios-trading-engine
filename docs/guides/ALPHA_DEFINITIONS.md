# Alpha definitions (step 085)

`helios.alpha.definition.AlphaDefinition` is the YAML-facing model for an alpha idea.
The examples in `configs/alphas/examples/` are illustrative DRAFTs, not selected
strategies or measured results. Hourly momentum and minute mean reversion use
registered feature names; the ML example is explicitly an untrained placeholder.

From the repository root in the documented WSL environment:

```bash
uv run python scripts/register_alpha.py \
  --file configs/alphas/examples/btc_hourly_momentum.yaml --check-only
```

`--check-only` validates without opening PostgreSQL. To persist a new definition,
omit that flag; the CLI owns a transaction and commits only after registration
succeeds. Database configuration comes from the existing environment/.env helpers.
Duplicate alpha_id/version pairs are refused. Change the version for a changed idea;
older definitions and their results remain readable.

The fields are `alpha_id`, positive integer `version`, `name`, `provenance` (QUANT
or ML), `feature_set_version`, `horizon_family`, positive integer `horizon_periods`,
`params`, `author`, and exactly one `expression` or `model_ref`. QUANT requires an
expression; ML may declare a model reference or a generated expression. Parameters
must be finite JSON values, including any nested values. Unknown fields, blank
identifiers/text, boolean or fractional version/horizon counts, and invalid commit
hashes fail validation. `code_commit` defaults to the current full Git commit.
Horizon periods count bars of the declared family; family names follow ADR-003.

Python usage:

```python
from helios.alpha.definition import load_alpha_definition, register_alpha_definition
from helios.common.db import get_engine

idea = load_alpha_definition("configs/alphas/examples/btc_hourly_momentum.yaml")
with get_engine().begin() as connection:
    registered = register_alpha_definition(connection, idea)
```

The adapter preserves the existing registry schema and its step-064 model:
YAML QUANT maps explicitly to database `human`, ML maps to `ml`; `expression` or
`model_ref` and `params` are stored in `spec_json`. The new YAML-facing model and
the older `helios.registry.api.AlphaDefinition` serve different boundaries. Neither
the database enum nor any accepted ADR is changed.

Registration inserts only a definition. Its initial lifecycle state is DRAFT under
`helios.registry.lifecycle.INITIAL`; there is currently no persisted lifecycle-state
column on definitions. No result, experiment, simulation, evaluation or promotion
is invented to represent DRAFT. The Python registration helper leaves transaction
commit/rollback to its caller. Examples are verified with rolled-back database tests
when the local PostgreSQL service is reachable.

Loading does not execute expressions or load referenced models. Step 086 provides
`helios.alpha.parser.parse_expression` for explicit structural whitelist validation;
see `docs/guides/ALPHA_DSL.md`. Step 088 now provides explicit pointwise arithmetic
evaluation with feature/scalar-parameter binding and availability masks. Step 089
adds the eight DSL functions, with explicit intervals for rolling/lag operations;
step 090 adds `helios.alpha.safety.validate_expression` and a semantic preflight
inside every evaluator call, checking all names, controls and branches before
series computation. Standalone validation uses declared feature names and scalar
parameters; it does not inspect data or load models.
Step 091 adds `helios.alpha.cross_sectional.evaluate_universe_expression` for
`cs_rank` and `cs_demean`, using explicitly declared per-symbol frames and historical
first-available dates. Single-coin evaluation rejects these calls; standalone
semantic validation requires `cross_sectional=True`. See the DSL guide for membership,
exact timestamp alignment and missing-peer availability rules.
Consequently successful YAML validation alone is not a causality or DSL safety
certificate. Definitions must pass explicit DSL validation and later simulator
evaluation before they can represent evaluated trading candidates.
Pre-register experiments before measuring performance, enforce chronological splits,
and preserve availability masks and result lineage during later evaluation.
