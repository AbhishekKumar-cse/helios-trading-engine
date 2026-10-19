# NSE share-unit and execution certification verdict

**NOT CERTIFIED.** The additional review verifies and diagnoses the retained
public evidence; it does not turn the conditional dataset into eligible trading
data. G7 remains false and TEST remains sealed.

`scripts/certify_nse_execution.py` reads only the retained January2025–June2026
prefix. It checks the v2 manifest and Parquet hashes, calendar/universe/session
checks, and the original, reconstructed and historical-member reference
collections against their snapshot-bound hashes and request journals.

The completed review covers **57 historical companies, 369 official reference
sessions and 18,468 observed stock-days**. It records daily high/low scale ratios,
minute-sum versus official daily volume, official EQ ISINs, retained action
events and per-company exclusions. Daily volume includes a different session
scope from the regular minute series, so equality is neither required nor proof
of correct minute volume. BE temporary listings lack an EQ comparison.

**41 companies remain conditional screen-only research inputs; 16 remain wholly
excluded. Zero companies receive independent raw-minute/volume certification.**
The exclusions include 13 conservatively quarantined capital-action histories
and three temporary BE listings. This preserves the accepted v2 cohort.

The observed largest daily-extreme relative differences include approximately
90% for BAJFINANCE, 80% for KOTAKBANK/SHRIRAMFIN, 50% for HDFCBANK/NESTLEIND and
33% for TRENT. These are adjustment diagnostics, not new share factors. Public
action records and daily EQ ISINs are retained separately; an API action row
carrying an obsolete ISIN does not establish a verified identity chain.

The [retrospective daily identity evidence](nse_action_identity_chains_20261018.json)
separately binds official EQ observations and price-basis regimes for all 16
excluded companies. BAJFINANCE changes from INE296A01024 to INE296A01032 between
the observed June 13/June 16, 2025 sessions; KOTAKBANK from INE237A01028 to
INE237A01036 between January 13/January 14, 2026; SHRIRAMFIN from INE721A01013 to
INE721A01047 between January 9/January 10, 2025. These transitions align with the
retained action ex-dates. This verifies retrospective daily identity facts,
not the legal announcement availability or original minute share/volume units.

For split/bonus histories, share ratios cannot reconstruct exact original raw
minute prices once a vendor has rounded adjusted prices. Rights/demergers also
require explicit treatment of entitlements and identity changes. A buyback is
not assumed to have rescaled every candle; its conservative quarantine remains
pending the same independent unit review. No inverse scaling or guessed volume
adjustment was performed.

The [Upstox historical endpoint documentation](https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/)
defines candle OHLCV fields. Those fields alone do not establish a dated
adjustment-vintage or raw-share-unit certificate for these particular retained
responses. The public corporate-action responses already collected remain
usable evidence; the separate authenticated provider action endpoint's retained
401 refusal was not bypassed.

| Obligation | Verdict | Evidence needed to close it |
|---|---|---|
| Raw price/share/volume units | Missing | Independent original minute vintage, dated adjustment and ISIN chain, including affected periods. |
| Causal availability | Missing | Contemporaneous membership/action/calendar publication times and an outage policy that does not select complete days using later knowledge. |
| Account costs | Scenario only | Dated account tariff and contract-note acceptance. The v2 statutory reference implementation and tests remain valid as scenario calculations. |
| Executable fills | Missing | Timestamped executable spread/depth and measured latency, participation and fill behavior. Last trade/OHLCV cannot certify 5bps slippage or capacity. |

The detailed local artifact is
`reports_out/nse_validation/20261018_certification1/certification.json`;
SHA-256 `0178eb6c16306677fa538db5c41d24a033f5280524d9b5af41a06cdb167058cd`.
The [compact per-company verdict](nse_execution_certification_20261018.json)
binds that artifact and snapshot manifest
`60b808fa29423fe7e0162d34fc24bed9d1fe0286c1c7a5f6869dccdb81706158`.
The full source responses, daily comparisons and datasets remain outside Git.

This closes the assessment with explicit failed certification. It does **not**
close the outstanding source/execution acceptance requirement or authorize a
gate waiver. Without additional independent evidence, a passing/promoted alpha
cannot be produced legitimately from this protocol, even if a future conditional
candidate reports positive P&L.
