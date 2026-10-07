# V4 real demand and supplier intelligence implementation plan

> For agentic workers: execute incrementally with Superpowers TDD and verification;
> independent focused components may use dispatching-parallel-agents. User authorizes
> continuous implementation after self-review and forbids all commits/pushes/tags.

Goal: extend one explicit research pipeline with optional read-only supplier data
and auditable compatible-offer decisions. Spec: v4-real-demand-supplier.md and the
approved user AI-Commerce-Agent-V4-Prompt.md. Contracts: v4-provider-contracts.md.
Python3.12/Pydantic2/HTTPX/SQLite/Streamlit. Existing393 tests are immutable.

Global constraints: isolated feat/real-demand-supplier-v4 froma0ad224; no commerce
wrappers; no secret persistence; no requests on reads/saves; no V3 score changes;
no FX; unknown monetary inputs are nullable. All writes remain uncommitted.

## Review focus
- Successful empty stock/price must invalidate current evidence, not resurrect it.
- AreaId cannot masquerade as storageId; quote must bind actual selected warehouse.
- Old selection/financial snapshots survive refresh without silent substitution.
- Quantity/destination/variant changes invalidate freight even with fresh timestamps.
- Failed/missing dimensions are null and fixed weights never inflate remaining scores.

## Task1 — models, matching and safe contracts

Create src/supply/models.py and matching.py; tests/test_supply_models.py,
test_supply_matching.py. Models are strict and timestamp-aware. Produce:
Destination(country='US',quantity=1,max_delivery_days=14,postal_code='',region='');
SupplierProductCandidate(provider,product_id,name,source_url,category,brand,image_url,
observed_at); SupplierVariant(provider,product_id,variant_id,name,sku,attributes,
unit_price,currency,weight_g,dimensions_mm,observed_at);
StockObservation(provider,product_id,variant_id,warehouse_id,storage_id,country,
quantity,cj_quantity,factory_quantity,observed_at);
ShippingQuote(provider,product_id,variant_id,warehouse_id,storage_id,origin,
destination,quantity,method,total_cost,currency,delivery_min_days,delivery_max_days,
tracking,observed_at,expires_at);
SupplierOffer(candidate,variant,stock,quote,match); SupplierSelection(offer,
confirmed_attributes,selected_at); all observations expose id and safe serialized data.
SupplierMatch(outcome,reasons,contradictions,missing_attributes).
ProviderOutcome(status,records:list[dict],partial,rejected,notice,observed_at).
ActionTelemetry(action_id,action,started_at,completed_at,requests:dict[str,int],
cache_hits:list[str],retries,stages:list[dict],elapsed_seconds).
SupplyIntelligenceReport(schema_version=4,product_id,input_fingerprint,destination,
offers,stages,telemetry,researched_at). Supplier matching
match_supplier(product,candidate,variant,destination)->SupplierMatch.

- [x] Write/run failing tests: unsafe links, missing IDs/UTC/nonfinite money,
  exact/likely/ambiguous/rejected identity, voltage/plug/count/brand/model/capacity
  contradictions, unit equivalence and missing decisive electrical fields.
- [x] Implement pure contracts/matching, run focused tests; no external calls.

## Task2 — allowlisted CJ transport/provider

Create src/supply/providers.py, cj_transport.py, cj_provider.py;
tests/test_cj_transport.py/test_cj_provider.py. Consumes Task1 types. Produce
SupplierProvider.search(query),details(pid),variants(pid),stock(vid),
shipping(variant,stock,destination)->ProviderOutcome. name='cj',configured boolean,
telemetry ActionTelemetry, set/reset action budget; optional transport/client fixture.
CJDropShippingProvider uses processCJ_API_KEY; UnavailableSupplierProvider no calls.
CJResearchTransport accepts operation enum/name mapped to fixed exact tuples,
validates params, scoped token cache/lock/expiry, count dispatches, max12/90sec,
>=1second spacing,20second HTTP timeout,2MiB response limit, <=1retry.

- [x] Red tests: auth disabled/expiry/refresh/concurrency/errors, allowlist bypass,
  redirects/forbidden hosts/methods/routes, request budgets/Retry-After/redaction.
- [x] Red fixtures for real listV2 nested shape/empty/partial/malformed/duplicates,
  variants USD/mm/g, separate CJ/factory stock, missing quantity, storage binding,
  quote fields and unavailable delivery/tracking. Implement and focused green.

## Task3 — additive storage and lifecycle

Create src/database/supply_repository.py/tests/test_supply_database.py. Modify
ProductRepository guard to accept VALID schema4 only (marker/table); preserve existing
test rejecting synthetic unknown4. MarketRepository.enable accepts active4 without
downgrade. SupplyRepository(repo,backup_dir=None).enable() ensures V3 first,
SQLite.backup into unique ignored path, verify schema3 and integrity, then transaction4.
Methods get/save_settings(product_id,Destination), get/save_report(report),
get/save_selection(product_id,selection|None),get/save_financial(product_id,snapshot),
get/save_shortlist(product_id,offer,label,notes),get/save_cache(key,outcome),
claim_action(action_id)->bool,save_action/get_latest_action; no writes from getters.
History append-only; current snapshot/outcomes transaction; cached UTC never rewritten.

- [x] Red tests schema3→4, WAL-safe backup, byte-identical old payloads, idempotence,
  transaction failure, immutable history, action dedup, selection/shortlist/reopen.
- [x] Implement, focused green; all393 baseline tests still pass.

## Task4 — financial/scoring primitives

Create src/supply/economics.py/scoring.py; tests/test_supply_economics.py/
test_supply_scoring.py. Produce FinancialInputProvenance(value,currency,unit,
source_kind,observation_id,observed_at,derivation), FinancialSnapshot(inputs:
MarketEconomicsInputs,currency='USD',provenance,revision,updated_at),
apply_supplier_cost(snapshot,selection,destination,now)->FinancialSnapshot,
apply_shipping_cost(...), save_manual_inputs(snapshot,inputs)->FinancialSnapshot.
SupplyScore/OpportunityScore each have dimensions raw nullable, weight,
contribution,evidence IDs,availability/reason,coverage,raw_total,final_score,
confidence,recommendation,risks,version. score_supply(selection,destination,financial,
stages,now=None),score_opportunity(market,selection,destination,financial,stages,...).
Formulas and gates exactly design; recompute only V4, never market-v3 mutating calls.

- [x] Red tests explicit application/no-match/likely confirmation/stale/wrongquote/
  mixed currency/unknown costs/provenance revision/manual preservation.
- [x] Red scoring tests fixed weights/null missing/coverage<60/mandatory gates/
  delivery threshold/single-provider, cheap-cost cannot become Strong. Focused green.

## Task5 — orchestration, shared UI and caches

Create src/supply/service.py/src/ui/supplier_intelligence.py;
tests/test_supply_pipeline.py/test_supply_app.py. SupplierIntelligenceService(repo,
provider=None).research(product,destination,force=False,demo=False,action_id=None)
->SupplyIntelligenceReport. research discovery one page10rows/3viable candidates/
2viable variants each;
freight only selected variant via refresh_shipping; refresh never alters selection.
Typed component caches request-complete; successfulempty currentcleared/failure
priorhistorical stale/malformedpartial separated. refresh_demand uses V3 provider,
independent ofOpenAI with explicit geography; stored V4 report noV3scoreoverwrite.
UI render_supplier_intelligence(product,repo), local save settings/selection/
Preferred/Backup/notes/cost application/manualV4 financial form and score breakdown.
Stable keys include product/provider/variant/warehouse/quote. Show pending stage
and explicit Refresh buttons. Extend products tabs and shared run_product_research
after V3 action, respecting Demo and independent CJ/OpenAI keys. Fix inherited
current-price empty/failure eligibility in V4 sidecar, not changing historicalV3.

- [x] Red integration tests provider independence, empty/failed/partial lifecycle,
  action consumption/no rerun duplicates, fresh caches and exact parameter keys.
- [x] Red AppTest multiple offers/quotes/keys, arbitrary main research, selection/
  confirmation/provenance saves/restart and zero navigation/request behavior.
- [x] Implement integration; run complete suite and quality checks.

## Task6 — actual acceptance, independent review, docs

- [x] Detect credential availability privately (booleans only); isolated DB/server.
- [x] Actual Electric heated lunch box UI, visibleUS/quantity1, optional one bounded
  live flow per configured provider; fixture flow explicitly labeled when keyless.
- [x] Save selections/costs/unknownzero handling; restart persistence/old saved views;
  verify0navigationrequests and exact counters; record sanitized evidence/artifacts.
- [x] Independent read-only reviewer full diff/security/provenance/scoring/migration.
  Reproduce material findings RED→GREEN; rerun final full suite/quality/secret scans.
- [x] README/docs/verification-v4.md complete all10requested reporting sections;
  not-live-verified text exactly as spec; recommendedV5 only, no implementation.
- [x] Indexempty/no commits; base/tags/main originalcheckout unchanged; V4readyreview.

## Plan self-review / rulings

All21prompt sections map toTasks1–6. User instruction overrides skill commit and
approval defaults. IDs and money units are not guessed. Valid schema4 marker solves
the existing future-version regression without weakening it. Independent pure
components may be delegated with exact contracts/files; parent owns sequential
storage/UI integration. Missing credentials do not stop acceptance. No unresolved
design placeholders or extra commercial capability. Worktree preserves originalmain.
