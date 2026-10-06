# V3 Market Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax. User explicitly authorizes continuous execution and forbids commits/pushes/merges.

**Goal:** Add trustworthy, explainable market intelligence to the one existing product-research action.
**Architecture:** Keep ResearchReport and legacy economics intact. Independent pure/provider modules feed a persisted versioned MarketIntelligenceReport through the existing shared UI action. Failure/caching/telemetry belong to this one orchestration boundary.
**Tech Stack:** Python 3.12, Pydantic 2, HTTPX, SQLite, Streamlit, existing OpenAI Responses SDK.
**Spec:** ../specs/2026-10-06-market-intelligence-v3-design.md

## Global Constraints

- Work in feat/market-intelligence-v3 at the user's existing checkout; v2.0.0 stays unchanged.
- Do not commit, push or merge. Preserve all existing 117 tests and V2 migration/economics contracts.
- Keep credentials environment-only and sanitized; no paid/external requests on navigation or save.
- DataForSEO is optional, disabled without both credentials. Its data is relative popularity, never monthly volume.
- UI says Supported on source page; this is publisher attribution, not objective truth.
- Record real per-run request/tool/cache/stage telemetry; never infer dollar costs.
- TDD: write tests, observe red, implement, focused green, full regression suite after integration.
- Independent units can execute concurrently in distinct owned files; storage/UI integration stays sequential.
- Reviewer is read-only and may not dispatch subagents. No production commerce/browser automation.

## Review Focus

- Mixed public/private DNS and rebinding: TCP endpoint is pinned, TLS hostname preserved (Task 2).
- Unknown new costs on V2 rows: legacy results remain known, V3 totals remain unknown (Tasks 1, 4, 7).
- Fresh cache over retained failed data: timestamps and latest attempt telemetry stay distinct (Task 5).
- Same product words but differing brand/pack or series geography: reject pooling (Task 3).
- Cached navigation after restart: no provider requests and old saved snapshots remain identical (Task 7).

## Task 1: Pure V3 landed/return economics

Files: src/services/landed_cost.py, src/services/market_economics.py, tests/test_market_economics.py.
Produces: LandedCostInputs (seven flat optional landed components),
calculate_landed_cost(inputs) -> float | None.
MarketEconomicsInputs extends landed inputs with selling_price,
payment_fee_percent, payment_fixed_fee, return_rate_percent,
estimated_loss_per_return, estimated_ad_cost_per_order.
calculate_market_economics(inputs) -> MarketEconomicsResult with
revenue_per_order, landed_cost, gross_profit_before_marketing, payment_cost,
expected_return_cost, contribution_before_ads, estimated_ad_cost, estimated_net_profit,
estimated_net_margin_percent, break_even_ad_cost, missing_inputs, complete.
Money boundary values are cents, Decimal-based calculations; unknown stays None.

- [x] Write tests for all-seven landed completeness; blank vs zero; fixed/percent fees;
  8% x12 =0.96; pinned net14.54/margin36.35/CPA22.54; negative outcomes;
  half-cent fees; invalid finite/range values; old calculate_economics still net15.80.
- [x] Run .venv/Scripts/python.exe -m pytest tests/test_market_economics.py -q; observe missing feature red.
- [x] Implement exact contracts and nullable dependency calculations.
- [x] Run focused tests and full suite; leave files uncommitted.

## Task 2: Safe public retrieval and publisher attribution

Files: src/research/providers/safe_http.py, page_verification.py,
src/research/verification.py, tests/test_page_verification.py.
Produces: SafePageFetcher.fetch(url) -> FetchResult with url, text, status_code,
status/reason, fetched_at, plus cumulative request_count/source_fetch_count counters.
Inject HTTPX transport, resolver and clock. fetch respects robots. Bounded deadline,
2MB decoded limit, two redirects, no credentials/proxy/cookies, global-IP pinning.

PageVerificationProvider.verify(source, claims: list[str]) -> VerifiedPage
with verification: PageVerification and html: str (ephemeral).
PageVerification contains source_id, canonical_url, publisher, page_title,
published_at/updated_at/date_status/date_provenance, accessed_at, fetched,
category, classification_reason, claims: list[ClaimVerification].
ClaimVerification contains claim, status, supporting_excerpt, confidence,
method; statuses exactly as spec. Types can live beside their provider to avoid cycles.
verification.py owns publisher_domain, classify_source, verify_claim and status_label.
status_label(VERIFIED_ON_PAGE) returns Supported on source page.

- [x] Write security tests for private/literal/IPv6/mixed DNS, rebinding pin,
  redirects/robots disallow, 403/challenge, unavailable HTML, size/deadline/content type,
  exact attribution vs partial overlap, no publication guessing, conflicting/future dates.
- [x] Run focused tests and observe red before implementing.
- [x] Implement retrieval, HTML visible text/metadata parsing and conservative claim support.
- [x] Run focused/full regression tests. No live third-party fetches in automated tests.

## Task 3: Optional demand, numeric trend and compatible prices

Files: src/research/providers/demand_trend.py, src/research/trends.py,
src/research/matching.py, src/research/providers/retail_prices.py;
tests/test_demand_trend.py, tests/test_market_prices.py.

DemandObservation: metric_name, provider, query, value, unit, period_start/end,
collected_at, source_url, confidence, notes, location, series_id, missing.
DemandResult: provider, query, location, observations, status, notice, collected_at.
DemandTrendProvider.collect(product) -> DemandResult, name, request_count.
UnavailableDemandProvider returns exact unavailable notice without a request.
DataForSEOTrendProvider reads both process env credentials, fixed official endpoint,
HTTPX injectable transport, no retries, no redirect auth; counter increments on attempt.
Requests one exact query, explicit US2840 default, closed past12months.
Validate root/task20000, matched keyword/location, dates and graph structure. Preserve
raw zero as missingness and separate raw index from calculated trend.

calculate_trend(observations, now=None) -> TrendResult with classification,
prior/recent_average, change_percent, observation_count, period_start/end, notes.
Require compatible uniform series, no conflicts/overlaps, two equal windows,
three samples per window and80% coverage, freshness30days. Prefer90days if supported.
Thresholds >=50/>=15/>-15/>-50 per spec, insufficient for prior<=0.

match_product(product, listing_name, brand=None) -> MatchResult(outcome,reasons).
MarketPriceObservation contains product_name, retailer, Decimal price, currency,
shipping_price, observed_at, url, source_id, availability, variant, brand, match_outcome,
match_reasons, reviewed=False.
extract_market_prices(html, product, source) -> list[MarketPriceObservation].
summarize_prices(observations) -> list[PriceSummary] grouped by compatible identity/
currency, count/minimum/median/maximum (nullable until>=2). No fetch in this parser.

- [x] Read Context7 and official Explore Live documentation before adapter implementation.
- [x] Write fixture transport tests for disabled/auth/error/malformed/index/period/location;
  numeric growing/stable/declining, sparse/stale/conflicting/missing data.
- [x] Write matching/price tests for multiple listings, median, currency, variants/brand/pack,
  duplicates, no metadata; observe focused red.
- [x] Implement the typed provider, pure trend and structured parsers, run focused/full tests.

## Task 4: Extension models and additive storage

Files: src/research/market_models.py, src/database/market_repository.py,
src/database/database.py, tests/test_market_database.py.
Consumes provider/economics types from Tasks1-3.
RunTelemetry contains UUID/run times/model, openai_model_requests,
web_search_calls nullable when unknown, page_fetch_count, page_request_count,
demand_requests, providers_used, cache_hits, stages: list[ProviderAttempt].
Stage attempts: stage/provider/status/collected_at/notice/retained.
MarketIntelligenceReport contains product_id/name/fingerprint/researched_at,
web_evidence:ResearchReport, page_verifications, demand, trend, price_observations,
price_summaries, economics_inputs, economics_result, score:MarketScore, telemetry,
risk_flags, schema_version3.

MarketIntelligenceRepository(ProductRepository) composes the legacy repo/path.
enable() atomically creates market_reports, page_verifications, demand_observations,
market_price_observations, market_economics, provider_attempts, provider_cache;
user_version3. First enable performs consistent backup to ignored artifacts.
No-op getters before schema3. ProductRepository allows existing version3 but still
initializes standalone V1->V2 at version2, never downgrades.
Methods: get_report(product_id), save_report(report), get/save_economics(product_id, inputs),
get/save_cache(key,payload,collected_at), save_run(product_id, telemetry), latest_run(product_id).
Cache payload may contain extracted metadata/prices, never full HTML or credentials.
Unique observation keys prevent duplicate rows; transaction preserves V1/V2 bytes.

- [x] Write V2->3 tests with byte-identical legacy records, V2 constructor version2,
  backup/readability, future-version guard, atomic failed writes, dedup/reopen and run retention.
- [x] Observe red; implement contracts; run focused/full regression suite.

## Task 5: Versioned scoring, orchestration and request accounting

Files: src/research/market_scoring.py, market_intelligence.py,
src/research/providers/web_research.py; tests/test_market_pipeline.py,
tests/test_market_scoring.py, tests/test_research_telemetry.py.
MarketScore contains version, dimensions, weights, contributions, raw_score,
confidence_factor, final_score, confidence, positives/missing, recommendation.
score_market_report(web,pages,demand,trend,prices,economics,now=None) -> MarketScore
follows exact weights/eligibility/thresholds from approved spec.

MarketIntelligenceService(repo,page_provider=None,demand_provider=None).research_product(
product, evidence_service, force=False, progress=None) -> ResearchReport keeps UI
return type. Creates telemetry; invokes existing V2 service once, then enriches its
persisted comparable evidence; stores report/run independently. V3 economics saves
recalculate MarketScore from stored evidence with no network.
Use injectable dependencies, separately keyed caches; default providers real only
on explicit requests. Suppress legacy retail fetch by using injectable price loader
during V3 runs; one safe page transport serves rich pricing/verification.
Instrument existing OpenAI boundary with optional event callback. Increment attempted
model calls before create/parse; count observed web_search items from actual response.
Do not infer counts from fake providers or force two calls. Mark unknown tool usage
on response failure. Clear counts per run; cache return means zero new calls.

- [x] Write seller-only/independent/stale/unknown/missing-data scoring tests and weights math.
- [x] Write partial stage failures, cached repeated research, force refresh, changed
  fingerprints, demo/keyless, preserved attempts/time and navigation-no-request tests.
- [x] Write real SDK MockTransport telemetry for two requests/observed tools and failure.
- [x] Observe red; implement; focused/full green; independent read-only architecture review.

## Task 6: Product Details/UI integration

Files: src/ui/market_intelligence.py, market_economics.py,
src/ui/research_details.py, products.py, dashboard.py;
tests/test_market_app.py. No second research action.
Keep legacy form/keys and original tabs; add Market Intelligence.
run_product_research composes Task5. Show refresh choice; bounded progress messages.
V3 form uses market_econ_<field>, prepopulates only unambiguous known references.
Show support labels/dates, relative units, compatible statistics, missing factors,
score breakdown, per-run actual request/cache/stage telemetry; costs unavailable.
AppTest fixtures inject HTTP transport/resolver, never production test detection.

- [x] Write tests for arbitrary/exact/category, support-not-truth wording,
  persisted known-date/unknown-date states, optional demand unavailable, V3 inputs,
  pinned metrics, telemetry, no requests while navigating/saving, old saved/Demo/keyless.
- [x] Observe red; integrate components; run complete suite preserving all117 tests.
- [x] Check secret/local ignores and diff scope.

## Task 7: Documentation, live acceptance and final review

Files: README.md, docs/v3-market-intelligence.md, docs/verification-v3.md.
Ignored artifacts hold logs/screenshots/backups/ledger, never credentials.
- [x] Run full pytest, Ruff, formatting, compileall and diff whitespace checks.
- [x] Independent read-only whole-branch review; reproduce material issues with failing
  regression tests and repair before final validation.
- [x] Start actual Streamlit UI; one Electric heated lunch box research from main input.
- [x] Record actual citations, page support/date statuses, prices/unavailability,
  request telemetry/model, optional demand status (fixture-verified only without credentials).
- [x] Enter manually40/10/5/zero other landed/3%/.30/8%/12/8, confirm net14.54/CPA22.54.
- [x] Restart actual server, confirm stored report/telemetry/economics/citations and old saved products.
- [x] Confirm Demo and isolated empty-key fallback; no more paid runs unless verification failure needs retry.
- [x] Update honest docs and completion report with18 requested items.
- [x] Verify branch/tag/main unchanged, original117 tests unchanged, local secrets ignored.
- [x] Leave all V3 changes uncommitted; do not push/merge.

## Pre-flight rulings / execution record

Task1 economics produces types consumed by4/5/6. Task2 page type consumed by4/5/6.
Task3 demand/pricing types consumed by4/5/6. Distinct files permit those pure
provider tasks to proceed concurrently under dispatching-parallel-agents while
the coordinator owns integration. No shared mutations between component workers.
The user explicitly authorizes implementation after these amendments and plan;
no additional design/plan approval is required. Existing feature checkout is used
as requested; no additional worktree. User prohibition on commits overrides
Superpowers default frequent commits. Progress ledger: artifacts/progress-v3.md.
