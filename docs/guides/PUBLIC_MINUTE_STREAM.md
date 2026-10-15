# Public closed-minute kline observer (154)

Use the documented WSL environment with the locked `websockets` dependency:

```bash
/home/abhi/.venvs/helios/bin/python scripts/stream_klines.py --seconds 600
```

The default subscribes to all five configured coins. Repeat `--symbol BTCUSDT`
to restrict the universe. `--endpoint data` selects Binance's public market-data
host; `spot443` and `spot9443` select its documented alternative ports. Endpoints
and paths are fixed public kline routes. No API-key/header/account configuration,
REST trade endpoint, order routing or database write is implemented.

The CLI writes JSON lines: session lineage, validated closed bars, then a bounded
session summary. It labels the session PAPER with execution disabled and prices
as observed public market data. PAPER is an execution-mode boundary; observed
prices are not synthetic fills. These records are not yet a registered historical
snapshot or the later `MarketDataSource` integration.

Only the Boolean `k.x=true` final update is printed. Symbol, stream and interval
must match the subscription. Exchange millisecond timestamps become integer
microseconds; the inclusive recorded close retains its millisecond precision.
Complete UTC-minute bounds, close availability, finite decimal OHLC/volume,
OHLC ranges, integer trade counts and taker-volume bounds are checked. Unfinished
candles produce no printed bar. Bad data fails visibly instead of becoming zero
or a fabricated observation.

`websockets` handles WebSocket control-frame responses. One connection is bounded
by a monotonic timer after its handshake; a stalled feed, disconnect, shutdown
event or malformed payload fails the observation. A duration with no closed bar
for a requested coin fails. This first part deliberately stops on failure.
Automatic reconnect and live gap detection remain step 159; no ten-minute
observation establishes the later 24-hour or network-failure acceptance tests.

Capture stdout/stderr to a new file under ignored `reports_out/`, retaining failed
attempts too. `SESSION_START` records commit/dirty state and exact client/CLI file
checksums; `SESSION_END` records connected duration and counts. These are data
observations, not alpha evaluation or profitability evidence. The client never
adds observations to the existing research snapshots or consumes TEST access.

Tests cover raw/combined payloads, incomplete candles, malformed/foreign data,
availability timing, unsafe symbol/endpoint input and invalid duration. Actual
loopback WebSocket tests verify deadline completion, filtering and visible early
disconnect without depending on Binance or the internet.

Batch verification passed 1,717 local tests, with one slow test deselected and
15 existing warnings. All 29 minute-profile/stream cases pass, strict typing
passes for 93 sources including this CLI, and repository lint/format and locked
dependency checks pass. Local database-backed tests run inside rolled-back
transactions; live data observations do not become research result rows.

The actual 2026-10-15 port-443 observation completed **600.003856194 monotonic
seconds**, receiving 1,316 updates and printing **45 closed bars, nine per coin**.
Each coin's observed opens are consecutive minutes. The system-clock timestamps
span 575.126185 seconds, so both elapsed values are retained explicitly; the
capture does not claim ten observed candle closes per coin or establish why the
clocks differed. Reproduce the endpoint selection with `--endpoint spot443`.

The first attempt on the market-data host stopped after eight bars per coin
because the 15-second idle guard fired. Its failed log remains separate and is
not counted as a completed observation. No automatic reconnect or source-code
change joined the two attempts. The [committed observation summary](../research/public_minute_stream_smoke.json)
records both log hashes, actual timing/counts and exact client/CLI hashes.
The capture ran during development with dirty state declared against `3f995b0`;
those byte hashes identify the observed implementation subsequently committed
for step 154. It is not presented as a clean-source alpha measurement.

Protocol sources, checked 2026-10-15:
[Binance public stream specification](https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md)
and [websockets asyncio client API](https://websockets.readthedocs.io/en/stable/reference/asyncio/client.html).
