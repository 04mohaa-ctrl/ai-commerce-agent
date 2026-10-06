# V3 market intelligence

V3 adds a versioned market report beside V2 evidence and legacy economics.
Run instructions in README remain valid. Existing saved V1/V2 scores and formulas
are preserved; V3 scoring is shown separately in Product Details.

## Research and cost behavior

Enter a specific product in the main Research field or browse a category.
Exact names select an existing candidate; unmatched names offer Research this
product. Both entry points use the same run_product_research action and existing
EvidenceResearchService/WebResearchProvider. V3 composes page, demand, prices,
economics and a deterministic report after the existing web-evidence stage.

Research product preserves V2's explicit fresh-web request behavior. Select
Reuse fresh web research to use the 24-hour unchanged-product web cache.
Page/price results independently cache for 24 hours, demand for seven days,
failed/unavailable results for one hour. Refresh all providers bypasses caches.
An explicit fresh attempt can retry a failed provider; routine cache reuse does
not. A newer successful web result supersedes its older failure cache.

Navigation, tab changes, saving products and saving economics make no external
requests. There is no background polling. Demo Mode and an empty OpenAI key
disable every external stage while keeping existing reports viewable.

Each research run stores its UUID, model, start/end, attempted OpenAI model calls,
observed web_search calls, source-fetch attempts, actual page GETs (robots and
redirects included), demand requests, providers actually used, cache hits and
sanitized stage outcomes. Failed retrievals with uninspectable tool output store
Unknown tool usage. Immutable run history is separate from retained successful
evidence. Request counts are not dollar estimates; unavailable costs stay unavailable.

Default web research uses gpt-4.1-mini, bounded to three search tool calls plus
structured classification. V3 does not add model-based page-verification calls.
At most six cited source pages are attempted with a shared 60-second read budget.
One page response is reused for attribution and listing extraction. Full HTML
is temporary and is never saved in SQLite/cache.

## Page support and publication dates

Public pages use HTTPS only, port443, checked global DNS and pinned TCP addresses
with the original Host/TLS SNI and certificate validation. Private, reserved,
local, mixed DNS and credential-bearing targets are blocked. Redirects are
revalidated and limited to two; decoded body size is limited to2MB.
Absolute socket/DNS/read deadlines, content-type checks, robots wildcard/anchor
and longest-rule matching are enforced. Malformed or inaccessible policies fail
closed. No browser retrieval, OCR, login/paywall/CAPTCHA/anti-bot bypass, proxy
inheritance, cookie persistence or third-party credentials.

Statuses: Supported on source page, Partially supported on source page,
Source reachable; claim unverified, Source blocked, Source unavailable,
Claim not found. Internal VERIFIED_ON_PAGE is never simply labeled Verified.

Support requires a long exact normalized contiguous occurrence of the actual
claim in visible page content. Overlap is only partial support; search-summary
excerpts alone do not qualify. This confirms attribution to that publisher,
not objective truth, semantic entailment by an independent verifier, or measured
consumer demand. Seller statements remain seller statements.

Valid page-specific publication/update metadata comes from JSON-LD or article
metadata. Unknown, contradictory, future or overflowing metadata stays unknown.
Access date is separate and never substituted for publication date.

Deterministic categories: seller, marketplace, manufacturer, news/editorial,
review/affiliate, forum, research/report, search/trend, other. Explicit affiliate
disclosure excludes independent-demand eligibility even with editorial metadata.
Unfetched pages may remain unclassified. Offline tldextract uses a bundled suffix
snapshot including private suffixes; different domains are publisher proxies,
not proof of different ownership. No suffix-list request occurs on navigation.

## Optional measured demand

The generic DemandTrendProvider supports future adapters. The first adapter uses
the documented native DataForSEO Trends Explore Live endpoint, with a single exact
product-name query and explicit location. Default: United States2840, previous
calendar year through yesterday. Provider/query/period/location/unit/collection
time and an independent normalization-series identity are preserved.

Set DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD in the process environment before
starting Streamlit. Both are required; missing either disables the adapter without
creating a request/client. Do not enter credentials in chat or store them in SQLite.
.env remains private for the existing OpenAI configuration; the DataForSEO adapter
reads process environment variables only.

Values are relative search-interest/popularity indices, never monthly search
volume or measured purchases. DataForSEO zero means insufficient data; raw zero
is retained with missing=True, excluded from trend arithmetic.

No usable provider: Measured demand data unavailable. The rest of research
continues. DataForSEO is fixture-verified; it was not configured or live-verified
during V3 acceptance. No unofficial Google Trends scraping is used. Google's
official API remains access-restricted alpha as checked 2026-10-06.

See [official DataForSEO Explore Live](https://docs.dataforseo.com/v3/keywords_data-dataforseo_trends-explore-live/),
[Google alpha access](https://developers.google.com/search/apis/trends), and
[HTTPX SNI pinning](https://www.python-httpx.org/advanced/extensions/).
Context7 library IDs: /websites/dataforseo_v3, /encode/httpx,
 /john-kurkowski/tldextract. Official endpoint examples take precedence over
unrelated Context7 merged-data snippets.

## Deterministic trend and prices

Trend uses one provider/query/location/unit/normalization series with uniform
closed periods. Identical duplicates collapse; conflicting/overlapping/future
bins reject the series. Two equal windows need at least three valid samples each,
80% coverage and a last closed period within 30 days. Prefer90days per window;
weekly data uses91days to keep whole bins. Missing bins are not interpolated.

Change =100*(recent average-prior average)/prior average.
>=50% strongly growing; >=15% growing; >-15% stable; >-50% declining;
otherwise strongly declining. Missing/sparse/stale/zero-baseline data yields
Insufficient data. Navigation recomputes freshness locally, so old numeric
classifications do not remain Growing indefinitely.

Prices come only from fetched Product/Offer structured metadata. Observations
store native currency, retailer, listing URL, original citation source identity,
actual page access time, availability, shipping when explicit, brand and variant.
AI price statements never become observed prices.

Exact compatible identity qualifies MATCH. Keyword-only LIKELY_MATCH is excluded
unless explicitly reviewed; ambiguous identity and brand/count/capacity/model
mismatches are excluded. V3 currently does not provide a manual likely-match
approval UI. No currency conversion or pack-size conversion is implemented.

Statistics need at least two compatible available unique URLs per brand/variant/
currency cohort. Conflicting prices for one canonical listing are excluded.
Show min, median, max, count and actual dates; median is a listing reference,
not a true market price. No matches yields Insufficient price observations.

## V3 economics, separate from V2

Seven explicit optional landed components: unit product cost, international
shipping, import duty, customs fee, packaging, handling, other variable unit cost.
All must be known for landed cost; blanks never become zero. Legacy shipping
is not automatically interpreted as international freight.

V3 adds fixed payment fee, return rate and loss per return. New missing assumptions
remain unknown even on old V2 records. All calculations use Decimal arithmetic,
half-up currency cents. Form assumptions are ESTIMATED; no LLM computes finances.

landed =sum(seven known components)
payment =cents(selling price*percentage/100 +fixed fee)
expected returns =cents(return rate/100*loss per return)
gross profit before marketing =selling price-landed
contribution before ads =gross-payment-expected returns
net profit =contribution-ad cost
net margin =100*net profit/selling price
break-even CPA =contribution

The loss per return is a manual assumption and should cover the intended
refund/logistics/recovery losses once. Sales tax and fixed overhead are excluded.
Outputs depend only on known inputs; negative profitability remains visible.

Example: selling40, unit10, international freight5, remaining landed costs
explicit0, fee3% +.30, returns8% at loss12, ads8:
landed15, payment1.50, expected returns.96, contribution/CPA22.54,
net14.54, margin36.35%. The old V2-only example remains15.80/39.50%/23.80.

## Confidence, prioritization and recommendation

market-v3 weights: demand evidence20%, numeric trend15%, competition15%,
return-adjusted profitability25%, marketing10%, evidence quality15%.
Raw dimension values, weights/contributions, raw score, confidence factor and
final score are shown. Unsupported dimensions contribute zero.
Profitability =clamp(net margin/5,0,10).

Demand reflects eligible independently attributed evidence coverage, not index
magnitude: zero without support; one/two/three publisher proxies give3/6/9.
Numeric trend points9/7/5/2/0; unavailable0. Qualitative competition/marketing
remain labeled AI judgements. Competition requires eligible page support;
unknown competition gives no advantage.

High requires three eligible independent domains, four supported independent
claims, >=75% dated-current publication metadata, fresh measured trend,
three fresh compatible prices, complete V3 economics and no stale component.
Medium requires two domains/two supported independent claims, >=50% dated current
coverage and usable numeric trend or two compatible prices. Otherwise low.
Seller-only stays low; missing measured data prevents high. Retained stale page
support and old web evidence lower confidence; reasons are visible.

Factors low.50/medium.85/high1.00. Final =round(raw*factor,1).
Insufficient evidence is first-class when independently supported demand or
complete net economics is unavailable. Strong candidate also requires>=75 and
high confidence; Worth investigating>=55 and at least medium; otherwise Weak.
This is a prioritization heuristic, not a probability of commercial success.

## Storage, backup and rollback

ProductRepository keeps plain V1->V2 initialization at user_version2 and can
read an already activated version3 database without downgrading.
MarketIntelligenceRepository explicitly backs up and activates a transactional
version3 extension on first V3 write.

New tables: market_reports, page_verifications, demand_observations,
market_price_observations, market_economics, provider_attempts, provider_cache.
Legacy tables and saved JSON bytes are retained. Observations deduplicate by
stable identities, not collection timestamps or mutable prices. Every telemetry
run is immutable; repeated identical writes are idempotent.

Failed stages retain comparable successful component data with original dates
and visible retention notices; changed product fingerprints prevent reuse.
V3 financial inputs persist separately, and current scores/risks recalculate
locally on read. Original report collection timestamps and telemetry stay intact.

Consistent pre-migration backups live in ignored artifacts/v3-backups.
Rollback to v2.0.0 needs that matching schema 2 database backup; do not run the
V2 code against the activated schema 3 file. The v2.0.0 Git tag is unchanged.

## Testing and limitations

Run .venv/Scripts/python.exe -m pytest -q and Ruff commands from README.
The suite preserves the original 117 tests/assertions and adds V3 transport,
numeric, migration, failure/cache, telemetry and AppTest coverage.
A shared fixture keeps default page transports offline for original UI fixtures;
security tests supply their own transports/resolvers. Tests make no paid calls.

Live results and restart checks are recorded in verification-v3.md. Only the
existing OpenAI provider and bounded page attempts were exercised live; structured
page support and DataForSEO success are validated with complete fixtures.
No facts/prices/dates are manufactured when sources cannot be safely read.
Conservative robots parsing, limited source coverage, lexical exact support,
matching ambiguity, publisher ownership uncertainty and missing optional metrics
limit confidence. There is no full historical analytics UI, supplier integration
or commerce automation. V4 should improve documented provider coverage and
reviewable product identity/page support before adding commerce operations.
