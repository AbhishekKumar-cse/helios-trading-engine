# NSE historical-cohort rebuild and new research round

The separate data/software rebuild and conditional research round are complete. Full source certification, profitable alpha and semester operational exit remain open.

Retained **6,909,518 actual minute bars across 57 historical companies**; **5,069,595 bars from 41 companies** pass the research screens. Removed 323,310 out-of-membership minutes. Original v1 files/results are preserved.

The reviewed calendar has 368 full sessions and 1 short session. Both Budget weekends and the 60-minute Muhurat session are explicit. Temporary demerged membership is separate from listing/series availability; dummy values are never traded.

Provider OHLCV is unchanged. Capital-action histories are quarantined instead of multiplying rounded adjusted prices into invented historical raw prices. Every scheduled date has an official daily reference; the fixed 0.2% scale screen remains weaker than minute/volume certification.

New fixed LightGBM fit: **505,528 TRAIN samples** and **152,405 separate TRAIN calibration samples**. No VALID fitting or hyperparameter selection, and no TEST access. The data cohort remains selected ex-post by its stated quality screens. Frozen 100-tree/15-leaf model, seed42; 21-bps approximate entry hurdle. Execution uses dated charge estimates, order brokerage caps, side-aware stamp and separate day-end STT settlements, plus the explicit 5bps/side slippage scenario and 2x replay.

| Candidate | Status | VALID Sharpe |
|---|---|---|
| momentum · RELIANCE | REJECTED | -179.543230 |
| reversal · RELIANCE | REJECTED | -309.208108 |
| ml · RELIANCE | INVALID | — |

Independent checks reconciled 43,665 base fills and 228 candidate/session replays, including fee settlements, ledger cash and stored metrics/gates. All 612 previous result artifacts retain their original hashes. Crypto registry remains 25 definitions/34 results; TEST0.

Verification: **1,830 tests passed**, one existing slow test excluded; strict types and Ruff pass. The measurements retain their original development dirty lineage when the implementation and evidence are subsequently published. Publication does not relabel the frozen research as a clean-source run.

G7 remains blocked. Still needed: certified raw share-unit/action/volume history for excluded observations, observed execution/liquidity/outage policy, market-hours PAPER acceptance and restart reconciliation, actual24h/7day trials and same-date comparison, and team evidence.

Open the [local lab](http://localhost:8501/?page=equities) and choose Rebuilt historical cohort. The original experiments remain selectable. See [ADR010](../decisions/ADR-010-nse-source-rebuild.md), [reproduction guide](../guides/NSE_REBUILD.md) and the companion JSON for exact paths, hashes, outcomes and exclusions.
