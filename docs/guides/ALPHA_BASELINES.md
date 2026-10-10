# Fixed hourly baselines (step 094)

| Baseline | ID | Expression | Formula parameters |
|---|---|---|---|
| B0 momentum | baseline_b0 | sign(log_return_24) | 0 |
| B1 reversal | baseline_b1 | -zscore(log_return_1, 168) | 1 |
| B2 taker flow | baseline_b2 | zscore(taker_buy_ratio, 168) | 1 |

The YAMLs in `configs/alphas/baselines/` declare version 1, feature set v1,
H-HOURLY and a one-bar forward target. B0's 24-hour historical lookback is separate
from that target. The plan's ret_1/ret_24 shorthand uses the registered log-return
feature names; no aliases are added. B1/B2 require 168 contiguous available values;
constant windows remain unavailable. All use the common bounded definition evaluator.

```bash
python scripts/register_baselines.py --check-only
python scripts/register_baselines.py
```

Check-only performs semantic preflight against the registered features without a
database connection. Registration inserts all three in one transaction, storing the
current commit, scale convention and parameter counts. Duplicate versions roll back
the whole batch; changed ideas require new versions, never edits.

Definitions start at DRAFT under the existing lifecycle contract (there is currently
no persisted lifecycle-state column). No experiment, result, evaluation or promotion
is manufactured. These are fixed comparison ideas, with no measured profitability.
