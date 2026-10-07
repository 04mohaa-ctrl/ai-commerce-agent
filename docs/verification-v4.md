# V4 verification and completion report — 2026-10-07

## 1. Release gate and Git state

The approved V3 gate passed before V4 implementation: 393 original tests passed,
lint/format/compile/whitespace passed, original main was clean, and local/remote
main plus peeled v3.0.0 were a0ad224404c3df071fed677fb0806f757f3f7bcb.
Historical 389 plus four V3 demand-retention regressions accounts for the baseline.
The unrelated PNG was preserved, with matching SHA-256, outside the repository at
`../ai-commerce-agent-local-files/uppgift3.png` before the gate was rerun.

V4 branch: `feat/real-demand-supplier-v4`; HEAD/base remains the V3 merge above.
Managed worktree: `C:/Users/Användar/.codex/worktrees/real-demand-supplier-v4/ai-commerce-agent`.
At implementation handoff, original main was clean and V4 intentionally had
uncommitted changes with an empty index. No commit, push, merge, tag or deployment
was performed during implementation. The user subsequently authorized saving V4
with a feature-branch commit and push; merge, release tagging and deployment remain
unauthorized. That Git handoff does not change the provider verification below.
Fresh read-only origin checks confirm unchanged main and annotated tag objects:

- v1.0.0: 5218bac11205d3632e58bf87e0ff4ea526c10568.
- v2.0.0: 4f0e50902da80d04a817c98b92470fbab8c248ba.
- v3.0.0: a4585946e556c723fb6b12fcfe54573046bac7d8.

## 2. Built behavior and files

One existing Research action now composes optional supplier and country-specific
demand stages. Product Details includes Supplier Intelligence, visible customer
country/quantity/delivery threshold, explicit offer selection, local shortlist,
independent component refreshes, separate V4 economics, provenance, deterministic
scores and actual request telemetry. All earlier research/citation/economics/demo
and saved-product flows remain available.

Modified: `.gitignore`, `README.md`, `src/database/database.py`,
`src/database/market_repository.py`, and `src/ui/dashboard.py`, `products.py`,
`research.py`, `research_details.py`, `settings.py`.

Added: `src/database/supply_repository.py`, `src/ui/supplier_intelligence.py`;
`src/supply/__init__.py`, `models.py`, `matching.py`, `providers.py`,
`cj_transport.py`, `cj_provider.py`, `service.py`, `demand.py`, `economics.py`,
`scoring.py`; ten `tests/test_cj_*.py` / `tests/test_supply_*.py` modules;
the four V4 design/plan/contracts/verification documents. No dependency changes.
All original tracked tests and conftest remain byte-equivalent in Git.

## 3. Models, storage and rollback

Strict UTC/Decimal models retain immutable observation IDs, provider/product/
variant/warehouse/storage identities, raw units, unknowns, request-bound freight
and separate selected/financial snapshots. SupplierProvider remains generic.
Nine additive V4 tables store settings, cache/current/history, selections,
shortlist, financial revisions and consumed action telemetry. Reads do not migrate.

An explicit V4 write creates a consistent SQLite backup, reserves a unique short
filename exclusively, verifies integrity and schema 3, then activates schema 4
transactionally. Failed backup/migration cannot silently advance storage.
History/current rollback, WAL consistency, old payload preservation, idempotence,
restart, schema guards and no downgrade are tested. Untouched V3 cannot read4;
rollback requires the matching pre-V4 schema-3 backup. Keep both databases; V4-only
records will not appear in the restored older copy.

## 4. CJ capabilities and authentication

Only exact HTTPS routes on developers.cjdropshipping.com/api2.0/v1 are callable:
POST authentication/getAccessToken and refreshAccessToken;
GET product/listV2, product/query, product/variant/query, product/stock/queryByVid;
POST logistic/freightCalculate. Auth/token expiry comes from documented responses.
Credential-scoped locked backend memory cache, timeout/body bounds, fixed method/
route/parameter allowlist, no redirects/proxies/cookies, conservative spacing,
bounded retries and Retry-After cooldown apply. Actual auth/retries count in budgets.

Actual stockId is required for freight warehouse binding; areaId is not storageId.
Quote total is USD for the exact vid/quantity; no CNY mixing or guessed conversion.
Country-only quoting is implemented. Postal/region freight and freightCalculateTip
are unsupported. No order/payment/balance/store/publishing/fulfillment capability.
Missing stock/price/delivery/tracking remain unknown. No supplier quality rating.

## 5. Demand availability and semantics

Generic V3 DemandTrendProvider and native DataForSEO Live adapter are reused.
Both process credentials are required; otherwise exact measured-unavailable
behavior is preserved. US2840, GB2826, SE2752, DE2276 and FR2250 were verified in
the official supported-country CSV linked by DataForSEO documentation.
Provider-relative search-interest/popularity is not monthly volume, sales or
buyers. Raw observations, dates, query/location and collected_at remain separate
from deterministic trend classification. One shared Research action reuses its
comparable V3 measurement; explicit standalone refresh makes at most one Live flow.
Navigation makes none. Unsupported geography dispatches none.

## 6. Decisions, lifecycle, finances and scores

Unit-normalized product/variant matching checks decisive brand/model/count/
capacity/plug/voltage details. Missing decisive facts cannot be invented through
confirmation. MATCH still requires selection; LIKELY requires confirmation of
actual attributes. AMBIGUOUS may be shortlisted, not used financially; NO_MATCH
cannot be selected. Definitely unrelated catalog rows and contradicted variants
do not consume viable enrichment budgets. Changed product inputs invalidate
current identity/observation eligibility until explicit research and adoption.

Successful empty clears current evidence, including every freight method in the
selected warehouse cohort. Failed/partial stages block current eligibility and
retain only labeled history. Refresh never replaces selection or applied costs.
Freight binds exact immutable variant/parcel snapshot and destination/quantity/
warehouse/storage. Explicit application creates financial revisions with observed
or derived provenance. Blank differs from explicit estimated zero. Incomplete
costs and incompatible currencies cannot claim complete profit. V3 arithmetic and
stored market-v3 reports remain unchanged. A read-only V4 overlay removes stale
retained retail eligibility after empty/failed current page fetches.

Supply weights25/20/20/15/10/10 and market-v4 weights18/12/12/25/8/10/15 are fixed.
Unknown raw dimensions are null, missing contributes zero without renormalizing;
coverage below60% makes the final score provisional/unavailable. Confidence is
applied once. Compatible selected stock/freight/cost, complete economics, current
independent market evidence and measured demand gate HIGH/STRONG. Cheap cost alone
cannot create a strong recommendation. Risk flags cite actual snapshots.

## 7. Live versus fixture product acceptance

Actual Streamlit ran on loopback8503 with an isolated ignored acceptance database.
Main Research field: **Electric heated lunch box**, **United States**, **quantity1**,
maximum delivery14days. Find/Analyze then Research this product opened the shared
flow. One genuine OpenAI web/search/classification flow completed with four cited
sources. Page support remained attribution, with unknown/blocked pages honestly
shown. No matching USD retail metadata was observed; economics remained unknown.
This verifies the OpenAI flow, not objective market truth.

CJ supplier adapter fixture-verified only. Live supplier data unavailable.
DataForSEO fixture-verified only. Measured demand data unavailable.

Both providers lacked credentials. No genuine CJ candidates, variants, stock,
freight or measured popularity were claimed. A separately labeled manual UI
fixture harness exercised offer vid1, 110V/US plug, warehouse area1/storage sub1,
stock20, USD5 unit cost and USD12 total fixture freight for one unit with5–10day
estimated delivery and unknown tracking. Those are simulated values, not CJ data.
Explicit selection, historical warning after quote refresh, re-selection/adoption,
cost application and manual packaging0/customsUnknown were verified in actual UI.
Navigation left fixture dispatches at exactly five. A second keyless actual-app
restart retained the selected variant, USD5 supplier cost, USD12 freight, explicit
packaging0, unknown customs and financial revision4. Demo Mode disabled refresh
buttons while showing retained observations. Original live citations stayed saved.
A local screenshot records the restored, explicitly fixture-labeled offer:
`C:/Users/Användar/.codex/visualizations/2026/10/06/01a110bf-ffe6-70a3-a95f-b7f446a369be/v4-supplier-ui.jpg`.

## 8. Tests, quality and independent review

Final pre-commit full run: **658 passed, 0 failed, 0 skipped**, 43.49seconds: original393 plus
265 new cases. PowerShell used the original Python3.12 environment and a unique
ignored absolute artifacts/pytest-git-save-UUID --basetemp because the machine's
default Temp fixture root has an ACL problem. Command:
`python -m pytest -q --tb=short --basetemp <unique-absolute-ignored-directory>`.
`python -m ruff check --no-cache .`: passed.
`python -m ruff format --no-cache --check .`:109files already formatted.
`python -m compileall -q src app.py`: passed. `git diff --check`: passed.

New tests cover auth/routes/retries/budgets/redaction, matching, currencies, stock,
freight, deterministic gates, migration/backup/rollback/restart, cache/lifecycle,
provider independence, no navigation calls, shared demand reuse, multiple widget
keys and first manual form submission. AppTest and manual browser evidence are
distinct. Actual live result/citations persisted across a keyless server restart.

Independent fresh read-only reviewer inspected approved spec/design/contracts,
all changed production code and new tests. It reproduced three P2 groups:
viable options hidden by cap order, obsolete identity after changed product inputs,
and first manual financial save resetting submitted values. RED→GREEN regressions
resolved each; reviewer reran264 V4 cases and found no remaining material issue.
Additional focused independent reviews found storage-ID filtering, parcel binding,
empty quote siblings, backup overwrite, shortlist method identity, percentage-unit
currency bypass and HTTP503 Retry-After. All were reproduced and fixed with tests.
No reviewer edited source or made live provider calls.

## 9. Telemetry, security and limits

Actual live run:2 OpenAI model requests,1 web-search use,4 page sources/fetches,
6 dispatched page-request attempts (including policy fetches),0 DataForSEO requests,
0 CJ requests. Used providers: OpenAI Responses and Public HTTPS pages. No guessed
dollar cost. Supplier and demand unavailable stages were persisted separately.
The manual supplier fixture recorded exactly search/details/variants/stock/shipping
logical operations; these are fixture counters, not network requests.
Navigation and the second keyless restart added no supplier actions: the persisted
latest action remained 2026-10-07T14:20:35.154946+00:00, four actions total. The five
fixture dispatches also remained unchanged. All temporary V4 acceptance servers
were stopped after verification; the original V3 app/server was left untouched.

Research supplier budget12 dispatched attempts/90seconds, one page10rows, at most
three viable products/two viable variants each; shipping4 including auth/retry;
demand one paid flow without automatic retries. Component caches preserve original
timestamps (catalog24h,stock/freight6h,demand7d,failed1h). Navigation and saves do
not dispatch. Reports distinguish cache hits, failed/unavailable/pending stages.

.env/environment/local DB/backup/artifact ignore rules were verified. Configured
secret values were privately scanned against intended Git files and isolated DB:
zero matches. No values were printed. Exact-route rejection and secret-redaction
fixtures pass. Index empty; no credentials or local artifacts are staged.

Not live-tested: CJ auth/catalog/stock/freight, DataForSEO measurements, account
specific limits/discounts. Unsupported: regional/postal freight and parcel-tip
API, FX, supplier quality/reliability verification, commerce transactions.
Prices/stock/freight may change; delivery estimates are estimates. Provider presence
does not verify quality. CJ listings do not prove demand; relative trends are not
sales; retail medians do not guarantee achievable prices. Scores are prioritization
heuristics, not probabilities of success.

## 10. Recommended V5, without implementation

Prioritize user-configured bounded live supplier/demand acceptance and independent
supplier/sample quality evidence before adding more providers. Consider a reviewed
currency source only if multi-currency decisions become necessary. No V5 feature
or commerce capability was started.
