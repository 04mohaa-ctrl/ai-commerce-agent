# V4 real demand and supplier intelligence

Approved specification: AI-Commerce-Agent-V4-Prompt.md supplied by the user.
Execution authorized after the release gate, with self-reviewed design/plan and
no further routine approval gates. No commit, push, merge, tag or deployment.

## Release gate — 2026-10-07

Private repository: 04mohaa-ctrl/ai-commerce-agent. Original checkout main was
clean after the explicitly authorized preservation of tmp/pdfs/uppgift3.png in
the sibling ai-commerce-agent-local-files directory (matching SHA-256).
Fresh non-destructive fetch confirmed local/remote main and peeled v3.0.0:
a0ad224404c3df071fed677fb0806f757f3f7bcb. V3 annotated tag object:
a4585946e556c723fb6b12fcfe54573046bac7d8.
V1 object5218bac11205d3632e58bf87e0ff4ea526c10568/targetaae060af00d6fa3f6e7efd8c5baa28e32395ad1d;
V2 object4f0e50902da80d04a817c98b92470fbab8c248ba/targetf2a365c71fbf5140c852c78d1220bf3ad5163501.
All refs agree with origin. V3 implementation9d7d62e and retention-fix ed6d9f1
are ancestors of main; no changes follow v3.0.0. Full393 tests passed in85.90s;
lint/format/compile/whitespace passed. pytest --collect-only collected393 before
this run; historical389 plus four parametrized retention regressions explains
the difference, without deleting/skipping assertions.

Managed isolated worktree: .codex/worktrees/real-demand-supplier-v4/ai-commerce-agent.
Branch feat/real-demand-supplier-v4 starts at the verified V3 merge. Original
checkout and release refs remain intact. Use the original Python environment
without copying credentials or the user's saved database into this worktree.

## Architecture and alternatives

Chosen: a V4 sidecar under src/supply with immutable observation snapshots,
independently cached component outcomes, explicit selection and financial provenance.
Compose SupplierIntelligenceService after the existing MarketIntelligenceService
inside run_product_research. Preserve all legacy contracts and market-v3 formulas.
Pure models/matching, provider transport, storage, service, scoring and UI are
separate units. No duplicate web research implementation.

Rejected: widening saved V3 payloads would silently change historical meaning.
A second supplier application would duplicate research/navigation and violate scope.
All V4 reads calculate only V4 current eligibility/freshness locally; stored
earlier scores and payloads remain immutable until explicit user actions.

## Provider safety and outcomes

SupplierProvider exposes search(query), details(pid), variants(pid), stock(vid),
shipping(variant, stock, destination). UnavailableSupplierProvider returns typed
UNAVAILABLE without requests. CJ is optional, reads process CJ_API_KEY only.
Outcome statuses SUCCESS, SUCCESS_EMPTY, UNAVAILABLE, UNSUPPORTED, RATE_LIMITED,
BUDGET_EXHAUSTED, FAILED; partial/rejected records, pending and freshness are separate fields.
Local dispatch-count or time-budget stops use BUDGET_EXHAUSTED; genuine CJ HTTP429
or rate/quota error codes use RATE_LIMITED. Typed limit_source distinguishes local
request/time budgets from provider rate/quota limits. retry_blocked_by retains a
local retry constraint alongside an actual provider RATE_LIMITED response.
The authenticated transport accepts named operations only, never a caller URL,
method, path or headers. Exact official host/method/path tuples are allowlisted.
No order/payment/balance/store/fulfillment wrappers, redirects, proxies, cookies,
personal address/tax fields or image downloads. Product links are sanitized HTTPS.
Requests have a20s timeout,2MiB decoded response cap and sanitized error code/status.

Backend token cache is credential-scoped, bounded, locked, and repr-hidden; use
returned UTC expiry,60s safety window, no credentials in SQLite/UI/session state.
One refresh or reacquisition on expiration; one authorized retry after token
invalidation. Serialize CJ calls at >=1s spacing per credential. Honor Retry-After
within the action deadline. A local-only deadline stop returns BUDGET_EXHAUSTED;
an observed HTTP429 remains RATE_LIMITED even when a retry cannot fit. Retry at most once for
documented system-busy/time-out or HTTP429/5xx; count every dispatch including auth.
No automatic demand retries when a paid completion is uncertain.

## Typed snapshots and market settings

SupplierProductCandidate, SupplierVariant, StockObservation, ShippingQuote,
SupplierOffer, SupplierSelection, FinancialInputProvenance, SupplyIntelligenceReport
and V4Telemetry have strict validators, UTC times, Decimal finite money, opaque
nonempty IDs and safe links. Observation IDs hash provider identity, request
fingerprint, time and sanitized content. Current snapshots refer to immutable
history. Cache reads keep original observed_at/fetched_at; selection has selected_at.

Customer market defaultUS visibly preserves V3 demand geography United States2840.
Country/quantity (positive integer), optional postal/region only if required,
and maximum acceptable delivery days14 are visible before research. This is the
target market, not a home address. V4 supports US/GB/SE/DE/FR country mapping to
documented DataForSEO country IDs; unknown mapping leaves demand unavailable.
Quote applicability includes provider/product/variant/warehouse/storage/origin,
country, quantity and parcel inputs; country/quantity/selection changes invalidate
current applicability without deleting history. No FX provider; cross-currency
economic application is blocked. CJ prices are native documented USD; tax inclusion
and account/quantity discount behavior remain explicitly unknown.

Freight uses documented freightCalculate, exact vid/quantity/start/end country and
storageIdList only for returned subwarehouse IDs. An areaId is NOT a storageId.
If warehouse binding cannot be established, report unsupported applicable freight.
Preserve logisticPrice USD quote total, optional taxes/clearance/totalPostage fields;
per-unit freight = quote total / quantity only for this exact one-variant request.
Do not interpret missing delivery or tracking as a promise. No freightTip fallback
when required parcel semantics are not established.

## Matching, selection and lifecycle

Reuse V3 deterministic names/brands/count matching with V4 unit normalization and
additional brand/model/plug/voltage/capacity/dimension contradictions. Explicit
variant contradictions are NO_MATCH. Missing decisive electrical attributes are
AMBIGUOUS; plug/voltage destination suitability must be observed. US110–120V/US
plug and EU/SE/DE/FR220–240V/EU plug expectations are displayed, not hidden.
Unit equivalence (500ml=.5L;10cm=100mm) prevents false contradictions.
MATCH remains explicitly selected. LIKELY_MATCH requires visible attribute
confirmation stored separately. AMBIGUOUS can be shortlisted but not used financially;
NO_MATCH cannot be selected. Never automatically choose cheapest or replace identity.

Successful data atomically advances only its own component and appends history.
Successful empty clears current evidence and leaves selected snapshots historical.
Failure retains prior observations with failed/stale attempt status and no fresh
score eligibility. Partial parses preserve validated rows and record rejection
count; wholly malformed arrays are FAILED, not SUCCESS_EMPTY.
Search, details, variants, stock and quotes have separate request-complete keys.
Catalog/details/variants TTL24h, stock/freight6h shortened by provider expiry,
demand7d; failures1h. Explicit component refresh bypasses only its cache.
Adoption of refreshed snapshots is explicit. Preferred/Backup/notes saves and
selection clearing are local-only. Historical selected identities never switch.

## V4 financial provenance

Reuse calculate_market_economics unchanged through a V4 FinancialSnapshot with
revision, currency, strict inputs and per-field provenance. Initial manual values
are copies, never a live alias of V3. Unknown remains None; explicit0 is ESTIMATED.
Only explicit Use observed supplier cost / Use current shipping quote applies
compatible fresh selected observations, displaying value/currency/identity/date.
Subsequent refresh does not replace them. Each derived output references the
financial revision. Any stale source makes eligibility stale without erasing
the historical value. Duty/customs/packaging/handling/returns/fees/CPA remain manual.
Known subtotal sums only known compatible unit costs; retail-minus-subtotal is
potential spread, not profit. Complete V3 formulas remain the definition of net
profit and break-even CPA. Missing cost or incompatible currency blocks totals.

## Deterministic scores

Supply weights match25/stock20/shipping20/completeness15/delivery10/freshness10.
Raw scores are nullable: match10 for MATCH,7 confirmed LIKELY; ambiguous <=3;
stock10 if fresh sufficient quantity,0 observed insufficient/out-of-stock,unknown
null; shipping10 applicable fresh quote,0 confirmed empty,otherwise null;
complete costs10,otherwise null; delivery10 within declared maximum,3 above,
unknown null; freshness10 only fully current required supply components,otherwise
null. Fixed weights do not renormalize. Missing contributes zero with explicit
penalty label; coverage is sum known weights. Below60% score is provisional/null.
No supplier reliability metric. Single CJ provider risk is always explicit.

User-facing supply aggregate and contributions use **0–10**, as requested:
displayed raw total = sum(raw_dimension × fixed_weight); missing contributes zero
without renormalization. Evidence coverage remains a separate percentage.
Stored supply-v4 aggregates/contributions retain their existing **0–100** compatibility
representation (ten times the displayed value). The UI divides those values by10;
stored scores, weights, gates and historical payloads are unchanged. Thus77.5/100
is displayed as7.75/10; STRONG75/100 and WORTH55/100 correspond to7.5/10 and5.5/10,
subject to all existing completeness/freshness/selection gates. This is a unit
conversion for presentation, not a new scoring formula or score version.
market-v4 aggregates and contributions remain **0–100**, explicitly labeled in
the UI; its raw dimensions, including supply feasibility, remain **0–10**.

market-v4 weights18/12/12/25/8/10/15 retain the approved demand/trend/competition/
profit/marketing/evidence/supply order. Use accepted V3 evidence gates, raw dimensions
and actual IDs, without using the confidence-adjusted V3 total. Unknown dimensions
are null, no unsupported observed zero. Profit uses complete compatible V4 inputs
and clamp(margin/5,0,10). Supply is its unadjusted score/10. Apply confidence once:
low.5/medium.85/high1. Coverage<60% makes final provisional/null and INSUFFICIENT
EVIDENCE. High requires V3 high evidence AND selected compatible fresh variant,
stock, cost, freight, complete economics and no pending/failed component. No measured
demand or supplier => no HIGH. Strong>=75/high plus every mandatory freshness,
selection, quote, stock and complete-economics gate. Worth>=55/medium and coverage;
weak observed performance requires available sufficient evidence; absent demand/
economics/selected supply => INSUFFICIENT EVIDENCE. No duplicate confidence penalty.
Risks reference snapshots: high freight if freight > unit cost, delivery above
declared threshold, missing delivery/stock/landed costs, stale quote and single provider.

## Persistence, budgets and acceptance

SupplyRepository activates schema4 only on explicit V4 writes, after a consistent
SQLite backup verified readable at schema3. Ensure V3 extension first for schema2;
ProductRepository accepts4 without downgrading, MarketRepository enable accepts4.
Transactional history/current/cache/settings/selection/shortlist/financial/report/
action tables preserve all legacy payload bytes. Same action UUID is consumed once
and prevents rerun duplication. No storage activation merely for viewing V3 or
Demo startup. Rollback requires matching pre-V4 schema3 backup; untouched V3 cannot
read4; preserve both databases and ignore backups/artifacts.

Default research CJ budget12 dispatches/90seconds, search at most2 pages x10,
enrich at most3 viable candidates,2 variants each, at most1 freight action for
explicit selection. Refresh shipping budget4 (including auth/retry), supplier12,
demand1 paid flow. Budget exhaustion returns partial/pending, never hidden calls.
V4Telemetry stores actual auth/search/detail/variant/stock/freight attempts,
retries/cache/elapsed and sanitized component outcomes, alongside V3 counts.
Startup/navigation/saved views/financial/selection/shortlist saves cause zero calls.
CJ/demand failures remain independent of OpenAI configuration except Demo globally
disables all providers. Dedicated demand refresh works without OpenAI.

Automated acceptance covers every user matrix area with real storage and injected
HTTP boundary fixtures. Actual Streamlit uses isolated ignored acceptance DB and
Electric heated lunch box, restart, explicit selections/application and keyless
fallback. Credentials availability is checked as booleans only. One bounded real
provider flow if configured; missing credentials do not block completion. Record
fixture/manual/live/unavailable/unsupported/not-tested evidence separately. Final
read-only independent review is required. No commerce capability or V5 work.

## Self-review

Requirements mapped to six incremental milestones. Distinct immutable snapshots
and component outcomes address failure/empty semantics; warehouse binding and money
units are conservative. User approval overrides further skill approval/commit gates.
No unresolved placeholders; provider contracts control actual parsing. Accepted
limits: single provider, estimated delivery, unknown price inclusions/discounts,
lexical attribution, no supplier quality rating, no FX or address collection.

## Final implementation and review amendments

The production discovery bound is one catalog page of 10 rows, enrichment of at
most three locally viable candidates and two viable variants per candidate.
Definitely unrelated catalog rows and contradicted variants do not consume the
enrichment cap. Matching remains conservative; option confirmation never supplies
missing decisive attributes.

Freight observations include `variant_snapshot`, binding the exact immutable
variant/parcel inputs, alongside actual storage ID and country/quantity. A refreshed
warehouse cohort replaces all shipping methods together. Successful empty clears
every current quote, while selected history and financial revisions remain intact.
Stage applicability distinguishes subwarehouse storage IDs. A changed product
fingerprint makes supplier identity and observations historical, including in UI
selection, financial application, scoring and freight dispatch.

Shortlist identity includes the full offer, so different shipping methods can
coexist. Backup files use short random names reserved exclusively; collisions
cannot overwrite earlier backups. Financial provenance validates per-unit,
per-order and percentage units by input field; currency checks cannot be bypassed
by relabeling money as a percentage. The initial unsaved financial form has a
stable owner across reruns; explicit observed application advances its revision.

The V4 demand sidecar reuses a comparable fresh V3 measurement and actual dated
observations, avoiding a second paid measurement in one Research action. Standalone
Refresh demand is independent of OpenAI. A read-only market eligibility overlay
removes retained retail evidence after successful empty page results or failed
current fetches, without rewriting historical V3 reports or score definitions.

Setup: supply and demand credentials belong in the app process environment only.
`CJ_API_KEY` enables CJ; both `DATAFORSEO_LOGIN` and `DATAFORSEO_PASSWORD` enable
DataForSEO. Missing credentials are unavailable, never a startup failure. OpenAI
retains the original local `.env` setup. No supplier credentials enter Streamlit
state, SQLite, HTTP error notices, fixtures or Git. Provider configuration is not
presented as verified connectivity. Current runs record actual attempts, caches,
retries, failures and elapsed time; costs are not invented.

Prices, stock and freight may change. Delivery estimates are estimates. Provider
availability does not verify supplier quality; a CJ listing does not prove demand.
Relative trends are not sales, retail medians do not guarantee achievable prices,
and opportunity scores are prioritization heuristics, not probabilities of success.
See verification-v4.md for actual live, fixture, manual and unavailable results.
