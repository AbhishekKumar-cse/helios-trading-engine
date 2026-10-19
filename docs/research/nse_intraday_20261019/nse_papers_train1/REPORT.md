# Paper-inspired NSE alpha research — 2026-10-19

Three executable research candidates were implemented and screened after costs. These are NSE adaptations, not replications of US performance. No candidate is certified, promoted, or claimed to pass the formal shared-engine gates.

## Literature and adaptation

1. **Closing momentum.** Gao, Han, Li and Zhou (2018) report that an ETF's early return, including overnight, predicts its closing half hour. [Peer-reviewed study — author university abstract](https://profiles.wustl.edu/en/publications/market-intraday-momentum/). The university abstract was read through the web tool; local retrieval returned403 and is retained. Publisher full text was not obtained. Our hypothesis trades individual NSE stocks long15:00–15:29 when their first30minute close exceeds the prior session close. This narrower stock/venue/long-only interpretation is our adaptation, not a result established by that paper.

2. **Opening range with relative volume.** Zarattini, Barbon and Aziz study opening-range breaks with elevated opening volume. [Full university-hosted working paper](https://www.alexandria.unisg.ch/server/api/core/bitstreams/3c2989c4-688d-4d78-8a71-f02690990d51/content). Our5minute range uses a positive opening candle, relative volume against14prior sessions, top20 available volume ratios, and completed5minute breakout confirmation. A closed-bar0.1ATR14 stop decision executes next open. Fixed capital replaces US dollar filters, leverage and risk sizing; intrabar stop fills are not assumed.

3. **Noise band with VWAP.** Zarattini, Aziz and Barbon use time-specific14day volatility bands and scheduled decisions. [Full university-hosted working paper](https://alexandria.unisg.ch/server/api/core/bitstreams/a99aba00-f967-49b3-aceb-f544dc386e0b/content). Our long-only adaptation uses a gap-aware upper band and an OHLCV typical-price VWAP proxy,30minute decisions, fixed shares and at most one entry/day. Its exit decision crosses the current band/VWAP; all fills use the following observed opening. No leverage, volatility targeting, US fee assumptions or published Sharpe was imported.

Heston, Korajczyk and Sadka document same-clock return continuation but explicitly discuss profits disappearing after spreads. [Author preprint](https://arxiv.org/pdf/1005.3535). This was reviewed as a cost/robustness warning, not added as a fourth candidate. AQR's [institutional cost study](https://www.aqr.com/Insights/Research/Working-Paper/Trading-Costs-of-Asset-Pricing-Anomalies) likewise motivates evaluating implementation costs; its institutional cost estimates were not substituted for NSE assumptions.

## Frozen experiment and measured TRAIN tail

The protocol was frozen before scoring: all41screened companies ×3candidates =123company/strategy comparisons, with all outcomes retained. Jan–Sep2025 is the development partition; Oct9–Dec31 is the existing reused TRAIN tail. October1–8 is not scored, but its already-observed bars may enter subsequent causal history. No new VALID price decoding or TEST access. Prior TRAIN/calibration and earlier VALID exposure prevent an independent OOS claim.

Each independently capitalized stock/day uses INR100,000 and a maximum INR50,000 target sized using the known decision close. Actual next-opening prices may drift from that target. Whole shares stay fixed until exit. The reference charge calculator includes statutory estimates and the current brokerage scenario; adverse slippage is5bps/side, doubled together with fees for stress. No risk/OMS/venue simulation, executable depth, account-contract-note reconciliation or capacity certificate is claimed for this TRAIN screen.

| Candidate | Tail active stock-days | Tail mean stock-day net bps | 2× cost net bps | Tail daily mean-account Sharpe | Frozen screen |
|---|---:|---:|---:|---:|---|
| closing_momentum | 1,043 / 2,003 | -4.9732 | -10.2166 | -17.3504 | Fail |
| orb_rvol | 152 / 1,399 | -1.5455 | -2.6421 | -13.0715 | Fail |
| noise_vwap | 442 / 1,399 | -2.6232 | -5.8083 | -12.2791 | Fail |

**0/3 strategy-level screens survive; 0/123 company screens survive the frozen stock-level rule.** These counts are exploratory, not multiplicity-adjusted discoveries. The frozen strategy screen requires at least40tail dates,20trades, positive mean net under normal/stressed costs, and all3tail months positive under both. Every company's full fit/tail outcomes are in results.json, including failures and insufficient-activity cases.

Mean-account returns average separate fully capitalized stock experiments. They are not an executable shared-capital portfolio, do not establish abnormal return over a benchmark, and should not be compounded into an investment track record. Trade timing, company coverage, different denominators and changed fee assumptions prevent comparison with the papers' reported Sharpe.

## Verification and remaining work

Five golden timing/future-perturbation/filter/no-reentry tests passed before the protocol was frozen. Independent verification reconciled 29,140 scenario fills, their original observed openings, pre-known quantities, dated charges and gross-minus-slippage-minus-fees. Every15session history window precedes its decision day, and normal/stressed runs use identical positions. All source/helper/protocol/result hashes were checked. Missing, short and quarantined days invalidate history rather than becoming invented zero returns.

This implements three research hypotheses; it does not create three proven profitable alphas. No repeated parameter search on VALID was performed. Source units, causal cohort availability, volume/VWAP quality, executable liquidity and account costs remain uncertified. G7 remains false. Sparse trading is also generally below the existing minute G3 minimum; the decision cadence and turnover units need an explicit reviewed protocol before formal evaluation. No gate thresholds were changed.

Any surviving lead still needs timing-matched market/cash controls, shared-engine integration for its fixed-share holding policy, independent confirmation after known data exposure, and the unchanged gates. If a screen fails, retain the failure rather than tune this tail until a winner appears. Existing main509866f and the scheduled PAPER test remain unchanged; no commit/push or real orders.

Files: definitions/*.yaml are research specifications, not production DSL registrations; paper_signals.py is executable candidate logic; study.py is the frozen runner; protocol.json, primary_sources/, source_receipts.json, source/, signal_tests.log, history_time_audit.json, decoded_scope.json, exclusions.json, session_records.json, results.json and verification.json retain lineage and every observation used. These local artifacts remain outside Git.
