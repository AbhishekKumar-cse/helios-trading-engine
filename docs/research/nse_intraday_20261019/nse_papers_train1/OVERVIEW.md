# Research-paper alpha prototypes

Three executable NSE research candidates are implemented in
[paper_signals.py](paper_signals.py). Their TRAIN results do not establish a profitable alpha.

| Candidate | Primary research | TRAIN tail average net bps per stock-day | With doubled costs |
|---|---|---:|---:|
| Closing momentum | [Gao et al., university abstract](https://profiles.wustl.edu/en/publications/market-intraday-momentum/) | -4.9732 | -10.2166 |
| Opening-range breakout with relative volume | [Zarattini, Barbon and Aziz, working paper](https://www.alexandria.unisg.ch/server/api/core/bitstreams/3c2989c4-688d-4d78-8a71-f02690990d51/content) | -1.5455 | -2.6421 |
| Noise band and VWAP | [Zarattini, Aziz and Barbon, working paper](https://alexandria.unisg.ch/server/api/core/bitstreams/a99aba00-f967-49b3-aceb-f544dc386e0b/content) | -2.6232 | -5.8083 |

These are adaptations to NSE stocks, long-only execution and Indian cost scenarios.
They do not replicate the papers' universes, portfolio construction or returns.
Gao's university abstract was verified; publisher full text was not obtained.
The other two full papers and the Heston et al. author preprint are retained locally.
The local refusal for Gao's page is also preserved.

The protocol was frozen before scoring all **41 screened companies × 3 strategies**.
Five causal timing/filter tests passed. An independent verifier checked **45,204
scenario/session records and 29,140 price-proxy fills**, including whole shares,
known decision-price sizing, next-opening execution, fees and doubled costs.

**None of the three strategy screens or 123 company/strategy screens passed the
frozen TRAIN-tail profitability and stability requirements.** Each company's full
results remain in [results.json](results.json); no favourable subset replaced the study.

The TRAIN tail is October 9–December 31, 2025. It was already used in earlier work,
so these results are exploratory. The mean returns average independent stock/day
accounts; they are not a single executable portfolio or benchmark-adjusted alpha.
No new VALID prices or TEST observations were decoded for this paper screen.

Each strategy permits at most one entry per day and holds a fixed whole-share quantity.
ORB uses the simple mean of 14 prior true ranges; its stop reference is the known
entry-signal close. Stops are checked at scheduled closes and execute next opening,
so the stop distance is not a guaranteed maximum loss. The noise strategy uses an
OHLCV-derived VWAP proxy. These choices are explicit deviations from the papers.

The three YAML files in `definitions/` are research specifications. They have not
been registered as production DSL alphas or evaluated through the full shared
risk/OMS/venue backtester. Source certification, holding-policy integration,
timing-matched controls and independent confirmation remain necessary. The current
minute turnover gate also needs an explicit decision-cadence review; no gate was changed.

See [REPORT.md](REPORT.md), [protocol.json](protocol.json),
[verification.json](verification.json) and [source_receipts.json](source_receipts.json)
for details. Preserve this directory; a new experiment needs a new directory.
Main and the scheduled PAPER test remain unchanged. No commit, push or real orders.
