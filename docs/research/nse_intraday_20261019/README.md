# NSE intraday research published October 19, 2026

This bundle preserves measured negative results and their executable research
helpers. It does not establish a profitable alpha or complete the semester's
market-hours PAPER requirements.

| Study | Scope | Outcome |
|---|---|---|
| [Certification and opening signals](nse_costaware_train1/REPORT.md) | Certification replay; four companies and three TRAIN signals | No certified histories; 0/12 exploratory survivors |
| [Original and reversed entries](nse_sign_reverse1/REPORT.md) | Six RELIANCE attempts through the shared evaluator, backtester, gates and registry | All REJECTED, each passing 3/8 gates |
| [Paper-inspired strategies](nse_papers_train1/OVERVIEW.md) | Three TRAIN-only prototypes across 41 screened companies | 0/3 strategy and 0/123 company screens passed |

The full per-company screen results are included, including all failures. The
paper screen independently reconciled 45,204 scenario/session records and 29,140
opening-price-proxy fills. The paired reversal verifier checked 127,028 base fills
and 684 candidate-sessions. All studies retained zero TEST accesses and zero
promotions. The paper screen did not create formal registry results or simulate
the shared risk/OMS/venue path.

## Source and publication lineage

The measured production source was commit
`509866fde6b13fa3fcfbb84d6ca0d0c51734954f`. Experimental helpers were uncommitted
when they ran. This publication does not re-execute the experiments or relabel
their source revision, dirty markers, protocols or results.

`manifest.json` binds every copied artifact to its original workspace path and
SHA-256. Files ending in `.py.source` contain the exact executed Python source,
preserved as historical evidence. They are intentionally outside the normal
Python import, formatter and test discovery paths. Historical Markdown statements
such as "no commit" describe the measurement time; this publication supersedes
them only for publication status. Relative helper links in historical reports
refer to the original retained folders. Here, append `.source` to Python links.

The reusable implementation is now in
`research/helios/equities/paper_signals.py`; its causal decision tests are in
`research/tests/test_equity_paper_signals.py`. Types and formatting were added for
publication. Golden timing tests and comparisons against the executed helper
verify unchanged decisions. This module is an exploratory prototype; production
DSL registration and holding-policy integration remain incomplete.

The original local folders remain under `reports_out/equity_research/`. They
retain raw minute inputs, frozen production source, model/calibration lineage,
receipt bodies, journals and large execution records. Those files are excluded
from Git, so this small bundle alone cannot independently replay market results.
A replay needs the original hash-matching inputs and production revision. Restore
archived helper filenames by removing `.source` in a separate scratch directory;
their original absolute paths, clean-source checks and exclusive output guards
must be reviewed before execution. Do not run them over an existing round, alter
old hashes, or reuse already exposed VALID data as fresh confirmation. Any portable
runner adaptation or new experiment requires its own source lineage and new
output directory. The archived source is evidence, not a new supported CLI.

## Interpretation and remaining work

Reversal means negating the directional expression before long-only clipping,
then rerunning execution and costs. It does not mean changing the displayed sign
of Sharpe or Fitness. Costs overwhelmed the measured gross returns.

The three paper prototypes adapt closing momentum, opening-range breakout with
relative volume, and noise-band/VWAP rules to NSE stocks. Primary source links,
access limits and method deviations are retained in the overview and protocol.
They use fixed shares, at most one entry per day and next observed opening prices;
the VWAP is an OHLCV proxy. Their averages describe separately capitalized daily
stock accounts, not a single executable portfolio or benchmark-adjusted alpha.

The TRAIN tail and earlier VALID outcomes had already been exposed. These are
exploratory results. Corporate-action/share-unit vintage, causal availability and
executable liquidity/cost acceptance remain unresolved. Gates were unchanged.
Before further formal evaluation, review decision cadence and the turnover gate
through an explicit protocol decision, add timing-matched controls and preserve
independent confirmation. The bounded October 21 PAPER test remains a separate
operational acceptance task.
