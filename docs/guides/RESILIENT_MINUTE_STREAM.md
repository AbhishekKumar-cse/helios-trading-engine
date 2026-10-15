# Public reconnect and gaps (159)

Run the public observer with `scripts/stream_klines.py --reconnect --seconds 600
--endpoint spot443`. It accepts a bounded duration up to 86,400 seconds; the
original single-connection observer remains available without `--reconnect`.
The session logs the reconnect policy's source hash and every connection change.
No account, API key, historical data mutation or real order route exists.

Network/handshake failures and idle connections reconnect with exponential delays
starting at one second and capped at 30 seconds. A connection lasting at least a
minute resets backoff. The overall deadline also bounds handshake, receive and
retry waits. Malformed observations, conflicting duplicate closes and consumer
failures propagate; they are not retried as network faults.

Each symbol has its own last closed bar. A repeated identical close is logged
and suppressed; older closes are logged and suppressed. Advancing beyond the
next minute emits GAP with expected/observed opens and the exact missing count,
before delivering the observed bar. No missing price, feature or bar is filled.
The first observation has no prior watermark and cannot prove initial coverage.
Watermarks belong to one process/session; process restart is a new session.

Five focused tests exercise a real local WebSocket disconnect/reconnect, replay,
two missing closes, out-of-order delivery, conflicting content, idle retries with
capped backoff, and consumer ValueError/OSError/TimeoutError propagation. The
retained [`minute_reconnect_fault.json`](../research/minute_reconnect_fault.json)
records the independent bounded fault harness: two connections, one forced
disconnect, four updates and two delivered synthetic closes. Its source byte
hashes are explicit; development dirty lineage is retained. Synthetic candles
test transport behavior only. No physical network cable was disconnected and
no 24-hour public soak is claimed. The step-154 public capture is preserved.
