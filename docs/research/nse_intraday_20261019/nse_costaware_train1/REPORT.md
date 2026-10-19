# NSE certification and cost-aware TRAIN research — 2026-10-19

**Certification: NOT_CERTIFIED. No promoted or gate-passing alpha.**

The fresh source replay matches the prior complete certification report exactly except for its assessment timestamp: 57 companies, 369 official daily reference sessions and 18,468 stock-days. All source hashes/journals were rechecked. 41 companies remain conditional screen inputs; 16 remain excluded. No quarantine was lifted or guessed price/volume repair made.

Missing certification evidence: original minute/share/volume vintage and dated corporate-action identity/adjustment chain; contemporaneous availability and causal outage handling; account tariff/contract-note acceptance; executable spread/depth, latency and participation/fill calibration. OHLCV and matching daily aggregates cannot establish these facts.

The provider documentation defines candle OHLCV but does not establish the required adjustment vintage for our retained responses: https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/ . No authenticated refusal was bypassed. This is a repeatable failed certification assessment, not newly acquired independent raw-minute evidence.

## Cost-aware experiment

Preregistered 12 exploratory comparisons: AXISBANK, RELIANCE, SUNPHARMA and TCS × opening trend, opening reversal and opening breakout. Signals use the first 30 completed minutes; entry uses the next observed 09:45 opening and exit the 15:29 opening. Long-only, fixed whole-share quantity, one round trip at most per day; INR100,000 independent daily capital and INR50,000 maximum entry notional. No price-maintenance rebalancing. The 21bps opening-move threshold is fixed, not a model estimate of remaining-session edge.

Uses the hash-verified archived shared fee calculator with the existing brokerage/statutory scenario and 5bps adverse slippage per side. Stress doubles both charges and slippage. These opening proxies assume no latency and complete fills; no spread/depth/volume participation or risk/OMS simulation is claimed. This is a pre-backtest signal/cost screen, not an official shared-evaluator/registry result.

Decoded only January–December2025 TRAIN observations, with the existing October embargo; no new VALID prices or TEST data were decoded. Source byte hashing and certification cover the retained TRAIN/VALID prefix separately. The October–December TRAIN tail was already used for ML calibration and prior VALID outcomes are known, so these are exploratory comparisons, not fresh independent out-of-sample evidence. No model was retrained or entry hurdle lowered.

Frozen survival rule: at least 20 active calibration sessions, positive net at normal and doubled costs, and all three calibration months positive under both scenarios. Every outcome is retained; no tuning after scoring.

| Company | Signal | Tail trades | Tail net INR | 2× costs net INR | Survives screen |
|---|---|---:|---:|---:|---|
| AXISBANK | opening_trend | 20 | -981.88 | -3,012.78 | No |
| AXISBANK | opening_reversal | 18 | -2,658.84 | -4,482.40 | No |
| AXISBANK | opening_breakout | 2 | -9.85 | -213.40 | No |
| RELIANCE | opening_trend | 21 | -2,511.60 | -4,642.13 | No |
| RELIANCE | opening_reversal | 13 | -53.86 | -1,368.14 | No |
| RELIANCE | opening_breakout | 2 | -426.25 | -629.61 | No |
| SUNPHARMA | opening_trend | 10 | 773.57 | -240.27 | No |
| SUNPHARMA | opening_reversal | 23 | -1,195.57 | -3,525.87 | No |
| SUNPHARMA | opening_breakout | 1 | 239.24 | 139.18 | No |
| TCS | opening_trend | 14 | -288.83 | -1,690.18 | No |
| TCS | opening_reversal | 21 | -1,815.64 | -3,906.31 | No |
| TCS | opening_breakout | 2 | 84.15 | -121.30 | No |

**0/12 survive the exploratory screen.** No formal gates were run. Maximum diagnostic average per-bar turnover is 0.001173; unchanged G3 requires >0.01, so this low-turnover design also has a gate incompatibility. Gates remain unchanged and G7 remains false. Independent daily accounts must not be interpreted as a continuous compounded portfolio.

The existing one-minute ML calibration has maximum expected return 2.3824bps against the frozen 21bps entry hurdle. This diagnoses the existing short-horizon cost mismatch; it does not show that a longer-horizon model will be profitable.

## Verification and next decision

Independent checks reconciled every session's gross/net/fees/slippage, whole shares, zero-trade records, unique identities and causal signal-before-entry timestamps; rebuilt all candidate totals and survival decisions. The database fingerprints (definitions, results, experiments, TEST audit) are unchanged. Production source remains clean at the scheduled PAPER revision; no commits, pushes, schedule changes or real orders.

Do not launch a VALID search or promote these screens while certification is unresolved. Further research needs an explicitly preregistered longer-horizon expected-net-return target and a reviewed decision on the existing turnover criterion; a gate change requires an accepted protocol decision and cannot be used to relabel old failures. Obtain independent minute vintage/adjustment evidence before certification can pass. Public evidence may leave that requirement open.

Files: protocol.json (frozen before scoring), study.py and source/ (actual executable source), certification_full.json and certification_summary.json, decoded_scope.json, exclusions.json, session_records.json, results.json, registry_before.json, verification.json. All are local research artifacts outside Git; the experimental helper is not represented as committed production code.
