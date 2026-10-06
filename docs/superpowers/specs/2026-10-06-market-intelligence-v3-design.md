# V3 Market Intelligence — proposed design

Status: approved by the user; UI attribution wording and request telemetry amended
before implementation. Implementation is authorized without another approval gate.
Date: 2026-10-06.
Branch: feat/market-intelligence-v3.
User requirements: the complete attached V3 Market Intelligence request.
No V3 commits, pushes or merges are authorized at completion.

## Intent and success criteria

Extend AI Commerce Agent so a named product can be researched through current web
evidence, actual source-page support, measured demand when available, compatible
listing prices, explicit landed/return costs and deterministic recommendations.
This is a local research workspace, without commerce automation or background
polling. Missing observations remain unavailable. Publisher assertions and AI
interpretations never become independent market facts through citation alone.

Success requires every existing 117 test to remain passing, new tests covering
the supplied V3 matrix, independent read-only review, and one real research
initiated in the running Streamlit UI with restart persistence. No external
provider is described as live-verified unless actually exercised. No implementation
or database migration is performed during this design stage.

## Verified starting point

- main and origin/main: f2a365c71fbf5140c852c78d1220bf3ad5163501.
- Annotated v2.0.0 object: 4f0e50902da80d04a817c98b92470fbab8c248ba.
- v2.0.0 target: the same main commit. Tag remains immutable.
- Initial working tree was clean; requested branch has been created from main.
- Baseline: 117 passed in 59.47 seconds. No paid calls in the baseline suite.
- Existing .env, databases, artifacts, virtual environment and caches are ignored.

## Existing interfaces and constraints discovered

src/research/providers/base.py defines ResearchProvider.research(product, progress)
returning ResearchReport, a sanitized ResearchProviderError with optional partial
report, and product_fingerprint(name/category/description/tags).

EvidenceResearchService.research_product(product, force, progress) is the one
orchestrator. Both Research entry and Details use run_product_research. Preserve
its ResearchReport return contract and all arbitrary/exact/category routing.

WebResearchProvider uses two OpenAI Responses calls: bounded web_search retrieval
and structured classification. Tool annotations gate source identity and exact
search-report excerpts gate findings. Its existing retail loader is injectable.
Keep that code path; do not recreate OpenAI search/classification in V3.

ProductRepository stores V1 snapshots and V2 research/attempt/economics JSON.
Migration is additive and transactional, user_version 2. One existing regression
test explicitly checks that V1-to-V2 initialization ends at version 2.

V2 source models have no publication metadata. V2 confidence counts publisher
domains heuristically, caps web confidence at medium, and V2 scoring uses
25% demand, 25% net profitability, 20% trend, 15% competition and 15% marketing.
Do not change those functions or saved results into V3 scores implicitly.

EconomicsInputs and calculate_economics use nullable assumptions and Decimal
arithmetic. The legacy USD40/10/5/3%/8 example must remain net USD15.80, margin
39.50%, break-even CPA USD23.80. Existing UI keys econ_product_cost,
econ_selling_price, econ_shipping_cost, econ_payment_fee_percent and
econ_estimated_ad_cost_per_order must remain usable.

## Approach choice

Recommended: compose a versioned MarketIntelligenceReport alongside ResearchReport
and legacy economics. Add narrow provider contracts and a single enrichment stage
to the existing explicit research action. This preserves old snapshots and lets
each provider cache/fail independently.

Alternative: widen all legacy reports/economics/scoring into V3 types immediately.
This offers fewer models but makes old score meaning, missing new costs and strict
extra-forbid JSON validation harder to preserve. Do not choose it.

Alternative: a separate V3 research action. This isolates changes but duplicates
routing and lifecycle behavior, contrary to the user requirement. Do not choose it.

## Module boundaries

Create:
- src/research/market_models.py: versioned observations, verification, attempts,
  confidence/score breakdowns and MarketIntelligenceReport.
- src/research/providers/safe_http.py: one bounded, DNS-pinned public HTTPS reader.
- src/research/providers/page_verification.py: source-page fetch and metadata.
- src/research/verification.py: deterministic per-claim page support/classification.
- src/research/providers/demand_trend.py: DemandTrendProvider, unavailable provider
  and optional documented DataForSEO adapter.
- src/research/trends.py: validated time-series grouping and numeric trend.
- src/research/matching.py: deterministic product/variant matching.
- src/research/providers/retail_prices.py: structured listing observations using
  fetched pages, never model-generated prices.
- src/research/market_scoring.py: V3 confidence, score and recommendation.
- src/research/market_intelligence.py: compose/cache independent provider results.
- src/services/landed_cost.py: complete optional landed-cost inputs and totals.
- src/services/market_economics.py: V3 fees/returns/contribution calculations.
- src/ui/market_intelligence.py: measured signals, prices, quality and explanation.
- src/ui/market_economics.py: explicit V3 financial assumptions and formulas.

Extend existing repository, service and Product Details to compose these modules.
Keep existing economics, provider and result signatures available. Avoid unrelated
refactoring. Add tests per unit and integration boundary, not duplicate implementation
tests. Use Python/Pydantic/HTTPX/Streamlit already present; consider tldextract with
its bundled offline suffix snapshot for registrable-domain grouping. No runtime
suffix-list download is allowed.

## One research flow, caching and failure isolation

Research input -> run_product_research -> existing V2 web evidence ->
MarketIntelligenceService.enrich -> page verification -> demand ->
structured prices -> deterministic score/report. Persist the existing web report
before enrichment so a later stage cannot erase citations.

Enable V3 enrichment through the existing service configuration used by UI, retaining
legacy callable defaults for existing integrations/tests. Navigation only loads
persisted records and recalculates deterministic finances/scores locally.

The existing UI Research product action preserves V2's fresh web-attempt behavior.
An explicit "Reuse fresh web research" choice uses the cache for unchanged inputs;
service callers default to reuse. Page/prices/demand remain independently cached.
Provide an explicit force-refresh option for the selected components. Defaults:
web cache 24h, page/price cache 24h, measured-demand cache 7 days. Unavailable/failed
attempt cache 1h prevents repeated unsuccessful calls. Cache keys include product
fingerprint, canonical URL, claim hash, provider, region/query/period and schema
version where applicable. Old successes remain separately dated after failed refresh.

Budget one web research sequence (existing max_tool_calls=3, two model calls),
one demand request per configured provider, and at most six cited source-page
reads. Share page content between verification and price extraction in a run.
No LLM page verification call is needed. Do not exceed 60s total page-read budget.
Page content is temporary; persist bounded supporting excerpts and metadata only.

Stage failures record a sanitized ProviderAttempt with collected_at and status
SUCCESS/PARTIAL/UNAVAILABLE/FAILED/CACHED/DISABLED. Preserve prior same-fingerprint
successful component data with its original timestamp and mark retention explicitly.
Never attach old-fingerprint observations to changed products. Demo/keyless actions
make no external calls and do not overwrite retained usable V2/V3 evidence.

## Public HTTPS retrieval security

Reject credentials, non-HTTPS schemes, non-443 ports, local/internal names and
nonpublic literal IPs. Resolve DNS before every new origin/redirect; reject the
origin if any A/AAAA answer is private, loopback, link-local, reserved, multicast,
unspecified or otherwise not globally routable. Connect to a validated IP while
retaining original Host and TLS SNI/certificate verification. A validation lookup
followed by an unpinned hostname request is insufficient against DNS rebinding.

HTTPX documents Host plus sni_hostname request extension for pinned-IP connections.
Use no environment proxy, credentials, authentication headers, persisted cookies
or automatic redirects. Enforce at most two redirects with full target revalidation,
TLS checks, connect/read/total deadlines and a decoded-body cap of 2 MB. Limit
accepted page content to HTML/plain text; reject downloads and unsupported content.

Check robots policy under the same HTTPS/DNS/bounds rules; respect disallow. If the
policy cannot be safely established, skip and mark blocked. Stop on CAPTCHA,
login, paywall or anti-bot responses; do not retry through alternate identities.
No OCR, browser-based retrieval, access-control bypass or third-party credentials.

## Page support, dates and source classification

For each source record original/canonical/final URL, registrable publisher,
page title, metadata published_at/updated_at, accessed_at, date_status,
source category and successful-fetch status.

For each (source, claim) store the status, bounded page excerpt, method version
and verification confidence. Use the six requested statuses:
VERIFIED_ON_PAGE, PARTIALLY_SUPPORTED, SOURCE_REACHABLE_BUT_UNVERIFIED,
SOURCE_BLOCKED, SOURCE_UNAVAILABLE, CLAIM_NOT_FOUND.

VERIFIED_ON_PAGE requires a sufficiently long contiguous normalized occurrence
of the actual asserted claim in visible page content, with no change to numbers
or qualifiers. An exact quote from the search summary alone is insufficient.
PARTIALLY_SUPPORTED reports overlap for inspection without feeding verified-demand
or high-confidence gates. Reachable pages with no usable claim extraction remain
unverified. Never use word overlap as proof of semantic entailment.

Verification means the page supports attribution of that publisher statement,
not that the statement is objectively true or independently measured. Seller
marketing remains seller marketing after textual verification. The UI repeats
this distinction wherever VERIFIED is shown.

User-facing VERIFIED_ON_PAGE is labeled "Supported on source page", never just
"Verified". Explain beside it: this confirms attribution to the publisher,
not objective truth or independent market verification. Internal enum names
remain stable for persistence and tests.

## Per-run request telemetry

Persist an immutable run identity and timestamps with actual OpenAI model request
count, observed web_search call count, page-fetch/request count, demand-provider
request count, provider names actually used, component cache hits and sanitized
failed/unavailable stages. Count attempted requests immediately at the transport
boundary, including requests which later fail. Distinguish source-page attempts
from robots/redirect HTTP requests. Do not equate model requests with tool calls.
Unknown tool counts after a failed response are explicitly unknown, not inferred.
Cache hits are from this run only; cached observations retain their collection
timestamps. Retained reports do not overwrite the latest attempt telemetry.
Display counts and stage outcomes in Market Intelligence and store every run.
Navigation reads existing telemetry without making requests. Dollar costs remain
unavailable unless a provider returns a reliably attributable actual cost; do not
infer prices from request counts.

Extract dates only from valid article/JSON-LD/OpenGraph publication/modification
metadata tied to the page; do not use copyright, crawl or access date as publication.
Keep raw date provenance, precision and conflicts. Unknown/conflicting/future
publication metadata stays UNKNOWN; accessed_at remains a separate field.

Classification precedence: marketplace known-domain rules; seller Product/Offer
metadata and shop paths; manufacturer known-brand/domain relationship; forum;
research/report; news/editorial; review/affiliate; search/trend; OTHER.
Rules are deterministic and versioned; classification confidence/rule is stored.
Explicit affiliate/commission disclosures take precedence over generic news,
research and forum metadata, preserving the non-independent evidence exclusion.
Seller/manufacturer, affiliate or OTHER claims do not prove independent demand.
Registrable-domain counts are publisher proxies, not proven ownership independence.

## Demand provider selection and metric semantics

Official Google Trends is still access-restricted alpha per current documentation.
Do not add pytrends or undocumented Google scraping. The structured alternative
investigated is native DataForSEO Trends Explore Live:
POST https://api.dataforseo.com/v3/keywords_data/dataforseo_trends/explore/live.
It needs its own credentials and is opt-in; no account is created.

User-selected provider: optional DataForSEO Trends adapter, fully disabled unless
both DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD environment variables are configured.
The generic DemandTrendProvider and modular unavailable provider always exist.
Credentials are read only from environment variables, held in repr-hidden fields,
never included in reports/errors/logs/tests, and sent only to the fixed provider
HTTPS endpoint. No credentials are stored in SQLite or requested in chat.
Do not create a client or make a request when either credential is missing.
Default market is United States,
explicitly visible/configurable; default query is exact normalized product name,
never silently substituted with a category or synonym.

Persist metric_name/provider/query/value/unit/period_start/period_end/collected_at/
source_url/confidence/notes plus geography, granularity and series identity.
DataForSEO popularity is a provider-relative index, not monthly search volume.
Its zero denotes insufficient data, not proven zero consumer interest; retain
missingness explicitly and exclude zero-as-no-data bins from trend arithmetic.

No compatible configured source -> "Measured demand data unavailable". Provider
availability and sample measurement precision are separate from report confidence.
An optional provider is mocked in unit tests, never claimed live-tested without
its actual credentials and successful request. Missing credentials do not block
the app, other research stages, tests or V3 completion. During live acceptance,
mark DataForSEO as not live-verified if unconfigured; fixture verification is
reported separately. Preserve raw provider values independently of the trend
calculation. No unofficial Google Trends scraping is permitted.

## Deterministic trend

Group only one provider/query/region/unit/normalization series with uniform closed
periods; reject overlapping, duplicate-conflicting, future or invalid intervals.
Deduplicate identical bins. Never merge separately normalized API windows.

Require two adjacent equal-duration windows, at least three valid observations
per window, at least 80% expected coverage and most recent closed period ending
within 30 days. Prefer previous/recent 90-day windows if cadence supports them;
otherwise show the actual supported duration. Missing bins are not interpolated.

Change = 100 * (recent_mean - prior_mean) / prior_mean. If prior_mean <= 0,
classification is INSUFFICIENT_DATA with an explicit reason.
Thresholds: >=50% STRONGLY_GROWING; >=15% GROWING; >-15% STABLE;
>-50% DECLINING; otherwise STRONGLY_DECLINING. Calculate observation count,
window bounds, means and change; slope/volatility are descriptive extras only
when defined. Stale or sparse series stays INSUFFICIENT_DATA.

Relative index level cannot establish absolute demand magnitude. The LLM never
overrides a valid numeric trend or manufactures missing observations.

## Retail observations and matching

Use public structured Product/Offer JSON-LD and known metadata, using safe fetched
pages. Extend V2's injectable price loader by delegation where possible instead
of creating another retrieval implementation. Keep legacy USD observation output
for existing callers; V3 records richer native-currency observations separately.

MarketPriceObservation stores product name, retailer, Decimal price, ISO currency,
optional shipping, observed_at, canonical listing URL, source_id, availability,
brand/size/count/variant details and deterministic match outcome/reasons.

Matching outcomes: MATCH, LIKELY_MATCH, AMBIGUOUS, NO_MATCH.
Exact normalized identity with compatible explicit brand/count/size/variant
qualifies MATCH. Keyword-only similarity is LIKELY_MATCH and excluded by default;
a reviewed inclusion is explicit and auditable. Conflicting pack count, capacity,
brand or variant is NO_MATCH; missing discriminators is AMBIGUOUS.
Do not infer the identity of an arbitrary lunch box brand from its broad name.

One compatible observed listing per canonical URL/product variant. Mixed currencies
or pack sizes are displayed in separate groups, never converted or pooled.
Only available MATCH or explicitly reviewed LIKELY_MATCH records enter statistics.
At least two compatible unique listings are required for min/median/max. Show
sample count, actual observation dates, matching caveats and explicit
"Insufficient price observations" when the threshold is unmet.

## Economics compatibility and formulas

Preserve EconomicsInputs/calculate_economics and their V2 storage exactly.
Add versioned MarketEconomicsInputs beside them. Loading V2 records supplies
known selling price, product cost, percent fee and ad cost as editable references.
Do not map ambiguous old shipping automatically into international freight;
label the V2-only example separately. New fixed fees/returns/landed components
remain blank until entered, including when a migrated V2 record omitted them.

Landed inputs: unit_product_cost, international_shipping_per_unit,
import_duty_per_unit, customs_fee_per_unit, packaging_per_unit, handling_per_unit,
other_variable_cost_per_unit. All seven must be explicitly known (zero allowed)
for a complete landed total. No blank cost defaults to zero.

Return inputs: return_rate_percent (0..100), estimated_loss_per_return (>=0).
Payment inputs: payment_fee_percent (0..100), payment_fixed_fee (>=0).
Selling price positive; costs finite/nonnegative; negative output profit allowed.
Use Decimal(str(value)), half-up currency cents, consistent fee/return rounding.

landed_cost = sum(all seven landed components)
payment_cost = cents(selling_price * payment_fee_percent / 100 + payment_fixed_fee)
expected_return_cost = cents(return_rate_percent / 100 * estimated_loss_per_return)
gross_profit_before_marketing = selling_price - landed_cost
contribution_before_ads = gross_profit_before_marketing - payment_cost - expected_return_cost
estimated_net_profit = contribution_before_ads - estimated_ad_cost_per_order
estimated_net_margin_percent = estimated_net_profit / selling_price * 100
break_even_ad_cost = contribution_before_ads

Unknown dependencies yield unknown outputs, with dependency-specific missing fields.
Even a zero return rate does not silently provide a missing loss assumption.
No LLM estimates return rate. Explain that the entered loss per return must include
the user's intended refund/logistics/recovery losses to avoid double counting.

Pinned example: selling 40, unit 10, international shipping 5, remaining landed
components explicitly 0, fee 3% plus 0.30 fixed, returns 8% at loss 12, ads 8:
landed 15; payment 1.50; expected returns 0.96; contribution/break-even 22.54;
net 14.54; net margin 36.35%.

## V3 confidence, score and recommendation

Version scoring as market-v3; old V1/V2 saved score fields and formulas stay intact.
V3 appears separately and can become the current report's prioritization score
only where its basis/version is explicit. Do not overwrite old snapshots.

Weights: demand evidence 20%, numeric trend 15%, competition evidence 15%,
return-adjusted profitability 25%, marketing evidence 10%, evidence quality 15%.
Dimension values are 0..10; missing evidence contributes 0, with reasons.

Demand points reflect supported independent-demand evidence coverage, not relative
interest volume: 0 without verified independent support, 3 for one eligible domain,
6 for two, 9 for at least three. A seller's assertion never contributes demand.
Numeric trend points: strongly growing 9, growing 7, stable 5, declining 2,
strongly declining 0, insufficient 0. Competition advantage uses accepted independent
verified competition findings with existing weak/moderate/strong inverse 7/4/1;
unsupported competition contributes 0. Qualitative classification remains AI JUDGEMENT.
Marketing uses page-supported positioning at 3/6/9, explicitly AI JUDGEMENT.
Profitability = clamp(return-adjusted net_margin_percent / 5, 0, 10), unknown ->0.

Evidence-quality points: independent verified-domain coverage up to 3 points,
claim verification coverage up to 3, measured-series coverage 2, compatible-price
coverage >=2 listings 1, complete V3 economics 1. Display every numerator/denominator.
Apply freshness penalties before classification; unknown publication cannot be
called current publication. A recent fetch alone is not recent publication.

High requires all: >=3 eligible independent domains, >=4 page-supported independent
claims, publication/update dates for >=75% of scored independent claims within
12 months, fresh compatible numeric series, >=3 compatible fresh listing prices,
complete V3 economics and no stale component. Medium requires >=2 eligible domains,
>=2 page-supported independent claims, >=50% dated/fresh scored claims and at
least one of usable measured trend or >=2 compatible prices. Otherwise low.
Seller-only evidence is always low; missing measured demand prevents high.
Fresh listing threshold 7 days, fresh measured collection threshold 7 days.
A report fetch older than 7 days lowers one level; component staleness and unknown
publication are listed individually. Factors: low .50, medium .85, high 1.00.

Raw = sum(10 * dimension_value * weight); final = round(raw * factor, 1).
Recommendation: INSUFFICIENT EVIDENCE without any verified independent-demand
support or without net economics. Otherwise STRONG CANDIDATE only if final>=75
and high; WORTH INVESTIGATING if final>=55 and confidence>=medium; else WEAK
CANDIDATE. Show evidence limitations beside the recommendation. This is a
prioritization heuristic, never a calibrated probability of commercial success.

## Persistence and rollback

Use a transactionally activated version-3 schema alongside the V2 repository:
MarketIntelligenceRepository composes ProductRepository and upgrades on first
V3 use. Plain legacy ProductRepository initialization retains version 2 until
the extension is activated, preserving the existing explicit migration test.
ProductRepository must accept/read version 3 after activation without downgrading.

New tables: market_reports, page_verifications, demand_observations,
market_price_observations, market_economics, provider_attempts, provider_cache.
Use product/fingerprint/version keys for reports and compatible provider series/
canonical URLs/period keys for observations. Unique constraints and atomic upserts
prevent duplicate observations. Reads of an unused V3 extension return empty
without migration or network. Persist no page credentials or full HTML.

Use a consistent SQLite backup before first V3 migration of the user's local DB.
Preserve all existing table/payload bytes unless a user explicitly updates a saved
analysis. Rollback to v2.0.0 requires the matching pre-V3 database backup; do not
suggest running V2 against user_version 3. Store backup in ignored artifacts.

## UI

Keep navigation, arbitrary-product CTA, category discovery, Details keys,
Analysis/Data & assumptions/Score calculation/Research/Sources/Economics tabs.
Add Market Intelligence rather than removing useful V1/V2 views.

Market Intelligence shows measured-demand availability, provider/query/region/
period/units, deterministic trend math, compatible listing groups, source categories,
page verification/date statuses, confidence positives/missing factors, risk flags,
dimension/weight/contribution/factor/final score and versioned recommendation.

Sources shows page support and publication date separately from tool citation
access date. Economics keeps the legacy form and adds an explicit V3 landed-cost/
returns section with nullable input widgets, its own save action and formulas.
V3 financial saves recalculate reports locally without requests. V2-only values
are visibly marked as legacy assumptions excluding new costs.

Progress stages remain in the one Research product action. The UI explicitly
distinguishes OBSERVED metadata/metrics, VERIFIED publisher attribution, ESTIMATED
financial assumptions and AI JUDGEMENT. No overall confidence label conceals
unavailable components.

## Incremental implementation sequence and review gates

1. Pure models, matching and complete Decimal landed/return economics.
2. Additive extension storage and explicit backup/compatibility.
3. Safe HTTPS transport, deterministic page support/classification/dates.
4. Optional demand adapter and deterministic numeric trend.
5. Compatible structured retail prices with shared fetched content.
6. Confidence, scoring, retained partial results and shared-pipeline integration.
7. UI extensions, offline regression coverage, docs and independent review.
8. Full suite, one real UI research, manual economics, restart and safe fallbacks.

Each implementation task requires new failing tests, observed failure, minimal
implementation, focused passing checks, full suite and regression review.
Do not edit original assertions to accommodate an incorrect new behavior.
Test fixtures can inject transports/resolvers to prevent every unintended external
call in automated tests; never add a production test-mode branch.

## Acceptance coverage

Cover all user-supplied page/date/SSRF/redirect/body-size cases; DNS rebinding,
mixed public/private DNS answers, IPv6 and redirect auth/cookie isolation.
Trend tests include zero-as-no-data, conflicting/overlapping bins, stale and sparse
series, constant/growing/declining series and wrong-query/geography data.
Prices cover two retailers, median, currencies, brand/pack/variant incompatibility,
unavailable offers, duplicate canonical URLs and missing structured metadata.
Economics pins legacy outputs and the V3 example, blank versus explicit zero,
negative contribution and half-cent rounding.
Confidence tests cover seller-only evidence, partial support, stale/unknown dates,
missing measured data and difficult high-confidence requirements.
Migration tests verify V2 payload bytes, V1/V2 readability, atomic rollback,
extension uniqueness and all observation/economics/report reopening.
Pipeline tests cover each provider failing independently, retained old timestamps,
changed fingerprints, cache expiration and no requests on navigation/saving.
AppTest covers arbitrary/exact/category routing, legacy widget keys, new unknown
inputs, progress, persisted V3 sections, Demo Mode and empty-key fallback.

Live acceptance: Electric heated lunch box from main Research input, exactly one
web research sequence. Record actual sources, page/date statuses, actual measured
observations or unavailable status, actual prices or insufficient observations,
manual V3 economics, confidence/score math and selected API/model. Restart the
Streamlit process and verify reports, citations and assumptions. Check existing
saved products and Demo/keyless behavior. Stop and report precise sanitized
provider limitation if real access fails; do not manufacture a successful check.

## Documentation and finishing

Update README; add docs/v3-market-intelligence.md and docs/verification-v3.md.
Record providers/methods, formulas, heuristics, caching/budgets, security, honest
live results and limitations. Completion report covers all 18 requested points.
Leave the V3 branch uncommitted and unmerged for the user's review.
The detailed implementation plan is stored in
docs/superpowers/plans/2026-10-06-market-intelligence-v3.md. It was executed with
TDD after the user's approval and amendments; changes remain uncommitted.

## Documentation checked on 2026-10-06

Context7: /encode/httpx and /websites/dataforseo_v3. Context7's generic Trends
response also returned an unrelated merged-data endpoint; the Explore Live
contract must be verified against the official page before writing the adapter.
No library/API behavior is inferred from that unrelated snippet.

- Google official alpha access: https://developers.google.com/search/apis/trends
- DataForSEO native Trends Explore Live:
  https://docs.dataforseo.com/v3/keywords_data-dataforseo_trends-explore-live/
- HTTPX pinned-IP SNI extension: https://www.python-httpx.org/advanced/extensions/
