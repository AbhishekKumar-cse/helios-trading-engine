# Optional delayed public-data PAPER simulation

The user authorized accommodating public-data delays on October 22, 2026.
[ADR019](../../decisions/ADR-019-delayed-public-paper.md) records the separate
simulation contract. The strict profile remains the default.

## What changed

`--timing delayed_public` selects a fixed 120-second maximum observation age and
180-second pending-intent lifetime. Startup waits at most 180 seconds. Decisions
use actual receipt times, and fills require a provider trade timestamp after
order creation. An older quote cannot fill a newer order. Missing candles,
expired features, expired intents, future-clock errors, identity mismatches,
risk limits, operator kills and ownership failures remain guarded.

The version, purpose, timing limits and fill model are stored in the hashed
configuration. Artifacts and the dashboard identify delayed-data simulation.
Strict configuration serialization and the prior run's config hash remain
unchanged. Recovery and the dashboard kill command recognize both profiles.

The runner and observer now select the completed candle with the greatest
opening timestamp. Previously they selected the last response row, which is
the oldest row when the provider returns newest first. An unfinished current
candle is excluded before selection. This is a code bug separate from the
declared latency contract.

## Check against retained observations

The original run `nse_paper_1022_041719960789` remains FAILED. It started at
09:47:38 IST, ran its observation loop for approximately 66 seconds, and created
zero orders, fills or position/P&L checkpoints. Its database strategy is HALTED
and its durable automatic kill is retained. Operator-kill and process-restart
market-hours evidence remain incomplete.

An offline, in-memory recheck used all 28 original raw responses with no new
network requests or database writes. Every response's last row differed from
its newest completed candle. The newest completed candles arrived 30.443481 to
88.218645 seconds after closing. Correct timestamp selection and the separate
120-second simulation policy admitted two distinct consecutive candles.

That journal contains no execution quotes. The offline check created no orders
or fills and demonstrates neither profitable alpha nor a new 15-minute run.
The earlier strict failure has not been rewritten or relabelled successful.

Retained evidence under `reports_out/equity_closeout/`:

- `nse_paper_acceptance_20261022.json`: original failed acceptance.
- `delayed_public_receipt_check_20261022.json`: separate offline comparison and
  verified legacy config/hash compatibility.
- `delayed_paper_verified_tests_20261022.log`: final focused software checks.

Original artifact SHA-256:
`ba1b8818036fbc2da98a133a899f68af40543802f2e62f81cb8830642c820208`.
Original receipt journal SHA-256:
`2b1b00d644fecfcc605f22d7aaf0ef13e97688b2b83198171cd40018a7551bb7`.

## Software verification

Final focused regression: **66 passed, zero skips**, including strict/crypto
behavior, delayed receipt/order chronology, newest completed candle selection,
future and stale inputs, expiry without quotes, dashboard labelling and kill,
plus crash recovery and inventory preservation for both timing profiles.
Strict mypy checks pass for six changed implementation modules; Ruff passes
for nine changed Python files. These are software tests, including synthetic
fixtures and rolled-back database checks, not a new market-hours acceptance.

## Running a new simulation

From a clean, reviewed source revision during an actual normal NSE session:

```bash
python -m helios.equities.paper_runner \
  --run-id nse_delayed_unique \
  --calendar data/equities/nifty50_minutes/20261017_public_round1/nse_holidays_raw.json \
  --seconds 900 --timing delayed_public
```

The verification above used an uncommitted development tree on main. The user
subsequently authorized a scoped commit and a separate 10:15 IST simulation on
October 22. Its exact launch revision and runtime are retained in
`reports_out/equity_closeout/delayed_paper_ready_to_run_20261022.json`; its actual
outcome must be read from the new session's artifacts, not inferred from tests.
No TEST access, promotion, research gate change, real orders, new 24-hour/seven-day
trial or push is authorized by that bounded simulation.
