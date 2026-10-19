# Three reversed NSE entry signals — paired exploratory results

Three distinct inverse candidates were actually replayed, together with their three originals. These are opposite **long-entry** conditions, not short selling, score negation or a promise of profitable alpha. Every outcome is retained in the registry and lab.

| Pair | Original Sharpe | Inverse Sharpe | Inverse Fitness | Inverse net INR | Inverse 2× costs net INR | Inverse gates |
|---|---:|---:|---:|---:|---:|---:|
| vol_trend | -150.3124 | -150.0497 | -1454.6595 | -531,455.41 | -1,070,184.94 | 3/8 |
| body_reversal | -156.0477 | -119.8750 | -1186.3333 | -611,988.20 | -1,221,044.76 | 3/8 |
| gap_reversal | -38.6218 | -64.5426 | -640.0801 | -776,189.15 | -1,545,432.20 | 3/8 |

0/3 inverses have positive total net P&L under both scenarios. All promotion decisions remain blocked by G7 and any other failed gates. Sharpe/Fitness are recalculated from actual net session returns; no displayed sign was changed.

## Exact experiment

Fixed before the first new replay: RELIANCE, full retained 2026-01-09 through 2026-06-30 VALID period, reviewed v2 snapshot, unchanged INR100,000 independent daily capital/50% target allocation, whole shares, long-only, next observed minute opening, final observed 15:29 opening exit. Normal and doubled reference charges/slippage pass through the unchanged shared strategy/risk/OMS/simulated venue/INR ledger. No guessed corporate-action adjustment, data-quarantine release, gate change or TEST access.

Negation is applied to the directional expression BEFORE clipping to [0,1]. For each pair, independent signal checks verify identical availability masks, disjoint positive entries, and that their sum equals the clipped absolute directional magnitude. Simply negating an existing [0,1] output would not test the opposite long-only entry rule.

The existing TRAIN-only model/calibration was copied byte-for-byte solely as shared evaluator lineage. No model refit or ML candidate ran. These formulas were chosen after negative VALID results were visible; the reused VALID results are exploratory and cannot serve as fresh independent OOS confirmation. Conditional complete sessions were selected ex-post. Costs and executable liquidity remain scenarios.

## Cost attribution — all six attempts

| Candidate | Gross before slippage INR | Slippage INR | Fees INR | Net INR |
|---|---:|---:|---:|---:|
| original_vol_trend | -8,129.60 | 256,740.14 | 272,874.44 | -537,744.17 |
| inverse_vol_trend | 7,266.30 | 261,156.64 | 277,565.06 | -531,455.41 |
| original_body_reversal | 4,088.40 | 314,436.64 | 334,191.53 | -644,539.78 |
| inverse_body_reversal | -2,940.50 | 295,249.16 | 313,798.54 | -611,988.20 |
| original_gap_reversal | -342.20 | 306,458.27 | 325,712.56 | -632,513.02 |
| inverse_gap_reversal | -6,957.30 | 372,901.41 | 396,330.44 | -776,189.15 |

Gross P&L minus adverse slippage minus fees reconciles to the saved ledger. Opposite long-entry rules need not have equal/opposite gross P&L: availability, quantities, entry/exit timing and whole-share rebalancing differ. Independent daily capital is not a continuously compounded portfolio.

## Verification and lineage

All six attempts were preregistered before new scoring. The existing read-only round verifier independently checked 127,028 base fills and 684 candidate-sessions, dated fees and settlement, whole-share flat-end accounting, normal/stressed Sharpe/Fitness and every gate. Existing crypto definitions/results and global TEST counter are unchanged. See checks.json, signal_checks.json and paired_comparison.json.

Production Python/config files are byte-matched to main509866f and remain clean for scheduled PAPER. The actual runner is an archived uncommitted research helper and its hash is included in the protocol, preregistered parameters and result artifacts. Original dirty markers are preserved; reported=false. Source/ and the frozen runtime retain actual execution bytes. No commit, push, PAPER-schedule change or real order.

[Open the equity lab](http://localhost:8501/?page=equities), select RELIANCE and research round nse_sign_reverse1. The registry holds all originals and inverses with their actual status; every retained run has a hash-verified report. Further parameter changes require a new protocol, not replacing these results or searching this VALID period until a winner appears.
