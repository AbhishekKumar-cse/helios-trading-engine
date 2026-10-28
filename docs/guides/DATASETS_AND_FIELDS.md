# Datasets, fields, operators and alphas

WorldQuant's public BRAIN material distinguishes datasets, data fields and
operators. Its official training programme separately covers fundamental/model,
price-volume, options/relationships/vector fields and newly released datasets.
See [BRAIN](https://www.worldquant.com/brain/) and the
[official workshop topics](https://www.worldquant.com/brain/iqc/).
The public `/data` page returned a JavaScript shell during this review; no
account-specific catalogue, proprietary field definitions or dataset IDs were
accessed. The contracts below are HELIOS's implementation, not a BRAIN export.

## The distinction

| Item | Meaning | HELIOS example |
| --- | --- | --- |
| Dataset | A source collection with a provider, coverage, market, frequency and version | NSE financial-result filings |
| Data field | One defined variable, with units, shape, availability and missing-value semantics | Quarterly consolidated profit in INR |
| Operator | A transformation appropriate for the input's meaning and clock | Year-over-year change, observed-peer rank |
| Alpha | An economic hypothesis encoded with fields/operators and evaluated under fixed portfolio/execution settings | Rank companies by already-published quarterly profit growth |

A dataset can contain many fields. Adding a trailing operator to a closing price
does not create a new informational dataset. A dataset catalogue also does not
solve bad price adjustments or confer profitability.

The implemented catalogue is `helios.equities.field_catalog`. Each dataset has
its own ID, family, source, market, frequency and evidence/collection status.
Every field must reference an existing dataset; names must be unique. Missing
fields cannot be silently replaced with a similar-looking input.

| HELIOS collection | Example fields | Actual availability |
| --- | --- | --- |
| `nse_vendor_daily_v1` | `adjusted_close`, `volume` | Retained daily history; historical units/vintage uncertified |
| `nse_financial_filings_v1` | `filing_events`, `filing_available_at`, `quarterly_profit`, `profit_yoy_growth` | Public metadata/XBRL collection; exact field coverage measured per round |
| `nse_delivery_positions_v1` | `deliverable_quantity`, `delivery_ratio` | One retained schema sample; no collected research history |

News, analyst estimates, options and relationship fields are not currently
collected or represented as available inputs. A news-inspired formula cannot run
by relabelling volume as sentiment. Delivery quantity is gross settlement
delivery, not signed institutional buying or investor intent.

## Shapes and units

HELIOS scalar matrices have one value per observation time and instrument.
Event/vector inputs may contain several records and require an explicit reducer
before entering a scalar formula. Timestamp fields carry clocks rather than
numeric economic values. The catalogue rejects using its event/timestamp fields
as scalar alpha inputs; it does not claim general dimensional analysis of every
DSL expression or implement all of BRAIN's operators.

Quarterly profit is money in INR. Profit growth is dimensionless. A profit figure
is not interchangeable with EPS, net income attributable to owners, revenue,
cash flow, annual income or a cumulative year-to-date figure. Unsupported filing
taxonomies remain unavailable. XBRL `decimals="-7"` describes rounding precision;
it does not mean multiply an already reported INR amount by ten million.

## Availability before transformation

A September-quarter profit is not known on September30 merely because that is
its accounting period end. The public NSE metadata provides reported broadcast
and exchange dissemination clocks. The experiment uses the later reported clock
plus a fixed five-minute lag, then the following observed price-close proxy.
These are publication-time research assumptions, not independently captured
historical receipts or proof of original-vintage completeness.

Revisions affect features only after their own reported publication. A revision
of an old quarter must not become the latest fiscal quarter or reset a stale
current quarter's age. Both current and comparable prior-year facts must already
be known. Same issuer, period, consolidation and INR units are checked. A missing
or zero prior-year profit makes the ratio unavailable. No future observation
fills a past gap.

Only declared scalar as-of fundamental fields permit past carry, with a fixed
180-day expiry. Market prices and returns are not opted into this carry policy.
See the existing [DSL contract](ALPHA_DSL.md) for the separate guarded
`ts_backfill` implementation.

## One new hypothesis

Conceptual BRAIN-style notation for this experiment:

```text
rank(profit_yoy_growth)
```

where the underlying field is:

```text
(current quarterly consolidated profit - known same-quarter prior-year profit)
/ abs(known same-quarter prior-year profit)
```

This is year-over-year profit growth, not a measured analyst forecast surprise.
Its economic hypothesis is delayed response to earnings improvement. It is not
a copied proprietary BRAIN alpha or a claim that NSE cash trading matches BRAIN's
simulation configuration.

HELIOS evaluates the scalar `profit_yoy_growth` through its existing DSL, then
explicitly ranks currently observed peers in the recorded portfolio adapter.
It does not silently add another platform's `rank()` to the DSL or weaken the
existing strict complete-universe semantics of `cs_rank`. The experimental
portfolio requires at least20 known fields, selects the top10, uses equal weights
and rebalances every20 observed sessions. There is no borrowing or short side.
Consequently it is not a sector-neutral long-short BRAIN simulation.

The first frozen round is `reports_out/equity_research/nse_profit_growth_fields1`.
Its metadata collection, raw attachments, exclusions and field masks precede
portfolio measurement. A separate `nse_profit_growth_fields2` reuses the same
hash-verified raw responses with an explicit identity-schema correction: BSE-code
contexts require matching symbol, ISIN and code facts; explicit ISIN conflicts
are refused. Missing OneD contexts remain unavailable. No formula/settings
changes or repeated HTTP requests were used. The original outcomes are retained.

The corrected round has 335 usable quarterly facts across 41 companies and
9,822 finite YoY company-session values. TRAIN2022 remains all cash from sparse
coverage. Development VALID25bps fractional return is +48.96% versus +40.41% for
the matched eligible-universe control; candidate Sharpe1.55 is below control1.66.
It remains nonpromotable: missing monthly stability, uncertified source/cost
assumptions and an unaccepted daily policy. Full coverage, comparisons and
verification are in the [research report](../research/nse_brain_fields_20261021/REPORT.md).

The catalogue is a field-definition/collection contract; actual retained history
and exclusions are measured by each round's separate coverage manifest. A declared
field alone does not imply complete observations or eligibility. Financial data
comes from [NSE financial results](https://www.nseindia.com/companies-listing/corporate-filings-financial-results)
and the exchange's [XBRL information](https://www.nseindia.com/static/companies-listing/xbrl-information).

TRAIN2022 and VALID2023-24 have previously exposed price
outcomes, so any result is development evidence; TEST2025+ remains sealed.
No change to the accepted source exclusions, gate thresholds or scheduled PAPER
test is implied by adding a dataset or discovering a promising formula.
