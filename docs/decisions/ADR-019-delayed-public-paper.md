# ADR 019 Delayed public-data PAPER simulation

Status: Accepted implementation scope, 2026-10-22, following the user's explicit
request to accommodate public-feed delays for simulated trading. This adds an
optional timing contract to ADR009. It does not supersede strict-feed acceptance,
promotion rules, source certification or the semester's elapsed-trial criteria.

The October 22 strict attempt is immutable: 28 responses, no accepted bars,
orders or fills, and a safety halt after approximately 66 seconds. Investigation
also found an ordering bug: provider candles arrive newest first, whereas the
runner and observer selected the last row. Select the maximum completed opening
timestamp explicitly; filter out unfinished candles first. In the retained
responses, even the newest completed candle was 30.44–88.22 seconds old. A
changed contract is a new simulation, never a successful rerun of that strict
acceptance.

Keep strict timing as the default: five-second observation age, ten-second intent
age. Add `--timing delayed_public`, version
`nse_delayed_public_minute_paper_v1`, purpose `delayed_public_data_simulation`,
fill model `delayed_public_price_proxy_v1`. Fix the optional profile at 120 seconds
maximum observation age and 180 seconds maximum pending-intent age. Startup waits
at most 180 seconds. These are declared simulation assumptions chosen to support
public minute data, not a verified feed SLA or a latency estimate for a broker.
They cannot be selected silently or widened through strict config fields.

Retain actual exchange and receipt times. Decisions occur at receipt, with no
backdating. A received candle may inform a delayed decision; it never fills that
decision. A fill requires a genuinely later provider trade timestamp strictly
after the pending order's receipt-clock creation, and is accounted at quote
receipt with the existing explicit fee/slippage proxy. A repeated older quote
is retained as raw data and cannot fill a newer intent. Wait for a later trade
within the fixed expiry instead of relabelling the old price. A quote may cross
minute boundaries while a delayed feature is still within its 120-second limit.
Future-clock tolerance remains at most five seconds, not 120 seconds.

Independently halt on expired feature candles or pending intents even if another
feed continues responding. Preserve candle chronology, missing-minute rejection,
instrument identity, risk/exposure/loss limits, exclusive ownership, durable kill,
terminal cancellation and crash reconciliation. No manufactured exit fills or
inventory reset. Public last-trade data remain proxies, not executable BBO.

Version/purpose/limits/fill model are hashed into the config and stored in every
new session/artifact. Old strict configs retain their serialization and hash.
Delayed output explicitly carries `delayed_public_simulation_only` acceptance
scope. It cannot demonstrate strict-feed acceptance, profitable eligible alpha,
broker readiness, operator-kill/restart evidence or an unattended 24h/seven-day
trial. Preserve all earlier failures and do not change TEST or research gates.
