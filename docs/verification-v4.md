# V4 verification and completion report — 2026-10-07

## 1. Release gate and Git state

The approved V3 gate passed before V4 implementation: 393 original tests passed,
lint/format/compile/whitespace passed, original main was clean, and local/remote
main plus peeled v3.0.0 were a0ad224404c3df071fed677fb0806f757f3f7bcb.
Historical 389 plus four V3 demand-retention regressions accounts for the baseline.
The unrelated PNG was preserved, with matching SHA-256, outside the repository at
`../ai-commerce-agent-local-files/uppgift3.png` before the gate was rerun.

V4 branch: `feat/real-demand-supplier-v4`; V3 baseline remains the merge above.
The subsequently authorized feature-branch save is
`a5e44356faec13f0b520376c04ce316df03fbe97`. The bounded CJ acceptance and focused
regressions in section 11 are uncommitted changes on top of that save.
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

## 7. Initial live versus fixture product acceptance (before CJ configuration)

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

## 8. Initial tests, quality and independent review

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

## 9. Initial telemetry, security and limits

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

## 11. Bounded genuine CJ acceptance after local configuration — 2026-10-07 UTC

This later acceptance supersedes the initial CJ-unavailable result above. It does
not turn the earlier fixture observations into live evidence. The user configured
CJ_API_KEY locally. The existing V4 server used the original Python3.12 virtual
environment and a dotenv launcher; only configuration booleans/process metadata
were inspected. No credential value was printed or changed. DataForSEO credentials
remained absent; **fixture-verified only. Measured demand data unavailable.**

### Saved manual run: local budget exhaustion, not a demonstrated CJ rate limit

The latest manual Portable Blender/Sweden/quantity1 supplier action started at
17:44:32 UTC. It dispatched search1, details3, variants3 and stock5: twelve actual
requests, zero retries, with an existing authentication token. The next stock
attempt for variant1543179507706900480 returned RATE_LIMITED with the exact notice
`CJ action research budget exhausted.` Transport emitted this locally before
dispatch, so that operation made no HTTP request. There is no CJ HTTP429 or CJ
rate/quota error code establishing a genuine provider rate limit in this action.
The twelve-attempt research budget and shipping budget were not increased.

The original USD11 subtotal came from the saved V3/Demo product-cost assumption,
not an applied CJ observation. No compatible offer was selected, so shipping
refresh was guarded without dispatch and supply coverage was0%. Broad Portable
Blender identity also left decisive capacity/color unspecified. Confirmation must
not manufacture those product requirements or missing supplier facts.

### Isolation, cache reuse and incremental corrections

Actual Streamlit acceptance used loopback8504 and the ignored isolated database
`artifacts/live-cj-portable-blender-20261007.db`. The launcher loaded the worktree's
ignored local environment and used the real CJ provider, without response fixtures,
fake credentials, monkeypatching or network interception. The user's original
database and servers8501/8503 were preserved.

The isolated target retained the name **Portable Blender**, with explicit local
requirements **350ml, pink, USB rechargeable**, customer country **Sweden (SE)**,
quantity **1**, maximum estimated delivery **14days**. These are acceptance target
requirements, not invented provider observations. Copied V3 product-cost/selling
price inputs were cleared in the isolated target's V4 initial financial inputs;
the separately labeled saved Demo analysis is not live market evidence.

Twelve fresh, successful, genuine CJ component caches from the manual run were
copied with original timestamps. Query/provider request parameters remained the
same; matching was recalculated against the explicit target. No failed records,
simulated records or timestamp resets were used. Catalog freshness is24h;
stock/freight freshness is6h. Selected stock was reused, not fetched again.

Two reproducible matching blockers were corrected through failing regressions:
the second name-only identity check discarded explicit description options; an
explicitly observed USB-rechargeable device unnecessarily required unknown mains
plug/voltage. Color options now remain in the dedicated attribute comparison.
The narrow observed USB charging rule does not invent electrical specifications
or verify an included adapter. Bare USB is insufficient; observed mains/AC/adapter/
wall-charger/dual-power evidence prevents exemption. Independent review reproduced
two further safeguards RED: explicit target voltage/plug must remain required, and
mains facts in variant option labels must be considered. Both were fixed; the
reviewer independently exercised eight boundary cases and reported no remaining
material findings. Budgets, provider architecture and financial rules unchanged.

### Actual requests and explicit UI actions

One Find/Analyze action used existing catalog/details/variant caches, dispatched
authentication1 and stock2 successfully, and persisted its telemetry. The stock
requests were for variants1436889474071138304 and1543179507706900480; the selected
pink variant's genuine stock observation remained cached. The supplier action
recorded nine component-cache hits (search1/details3/variants3/stock2) plus one
token-cache hit. There were no retries or local/provider rate-limit failures.

The UI required observed-attribute confirmation and explicit selection of:

- CJ product1392009095543918592: 350ML Electric Juicer Blender Mixer USB
  Rechargeable Machine Household Portable Blender Maker Cup Kitchen Tool Kit.
- Pink variant1392009096907067392, SKU CJJD112318803CX, 350ml capacity from the
  observed title and Pink from the observed variant_key. Classification:
  LIKELY_MATCH, no contradictions/missing decisive attributes; explicit confirmation
  retained. Included mains adapter and food-contact safety remain unverified.
- Warehouse/area1, actual storage2991a224-737b-42a3-a1d9-8ccd2936b341, originCN:
  total2, CJ2, factory0, observed17:44:37 UTC. Factory-only storage rows were not
  substituted for this CJ inventory. Supplier unit price USD17.19, observed
 17:44:35 UTC; declared parcel660g,310/170/140mm.

One explicit Refresh shipping dispatched one genuine freight request and returned
twelve methods at21:02:19 UTC, bound to that immutable variant/parcel, actual
storage, destinationSE and quantity1. Refresh retained the old selection as history;
it did not silently adopt costs. The UI explicitly confirmed/re-selected
**CJPacket Eub Special Line, USD19.34 total, estimated8–12days**, within the14day
target. The cheaper USD14.43 method estimated12–20days and was not selected.
Tracking remained unknown. No postal/region address or conversion was invented.

Across this isolated live acceptance, actual CJ dispatch totals were:
**authentication1 + stock2 + freight1 =4**, retries0. Catalog/details/variants
requests during this acceptance were0, relying on genuine earlier live caches.
Shipping reused the authentication token once more. OpenAI requests0, web-search
uses0, page fetches0 and DataForSEO requests0: those optional stages were unavailable
without worktree credentials. Persisted actions: supplier1, unavailable-demand1,
shipping1. Provider actually used: CJ. No inferred dollar API cost was reported.

### Finances, scoring, restart and navigation

Explicit Apply observed supplier cost created revision2 with USD17.19 OBSERVED
provenance linked to the variant observation. Apply current shipping quote created
revision3 with USD19.34 DERIVED provenance (quote total divided by quantity1),
linked to the quote and its original timestamp. Saving explicit packaging0 created
revision4 with ESTIMATED provenance; blank customs remained UNKNOWN. Product cost
and shipping retained their observed/derived provenance after that manual save.

Known compatible unit subtotal: **USD36.53**. Duties/customs, handling, other costs,
selling price, payment fees, returns and advertising remained unknown. Consequently
complete landed cost, net profit and break-even CPA remained Unknown. The quote's
provider-reported taxes_fee0/clearance_operation_fee0 were retained as quote data;
they did not establish complete import/customs liabilities or auto-fill finances.

Supply score: **7.75 / 10** (stored aggregate **77.5 / 100**), coverage **85%**, confidence **low**, recommendation
**INSUFFICIENT EVIDENCE**. Cost-completeness contributed zero with15% coverage
missing; on the displayed0–10 scale, LIKELY match contributes1.75, stock2,
freight2, delivery1, freshness1. The initial live UI showed the stored77.5 without
a denominator; section12 records the presentation correction without new provider requests.
Actual risk flags: SINGLE_PROVIDER, INCOMPLETE_LANDED_COST and HIGH_FREIGHT
(USD19.34 freight exceeds USD17.19 product cost). Overall market-v4 opportunity
coverage15%, score unavailable/provisional, low confidence; no HIGH/STRONG claim.

Settings/Saved Products/Supplier Intelligence navigation added no requests. The
isolated server was stopped, restarted with the same database, and the actual UI
restored selected variant/storage/quote, observed/derived provenance, packaging0,
unknown customs and financial revision4. Default Demo Mode disabled external
refresh buttons while retaining genuine observations. The three persisted action
payloads remained byte-equivalent across navigation/restart (SHA-256
7a52ad78eb6838121a1667225ff1d2092daf5fb8569c38154f63c73cf0d5be0b); dispatch totals
remained4. No research/refresh action was issued after restart. Live UI proofs:
`C:/Users/Användar/.codex/visualizations/2026/10/06/01a110bf-ffe6-70a3-a95f-b7f446a369be/v4-cj-live-economics.jpg`
and `v4-cj-live-score.jpg` in that same directory. These show persisted genuine
observations in Demo Mode, not fixture-generated data.

Final regression suite after all focused corrections: **668 passed**, zero failed/
skipped,123.77seconds. Ruff lint passed; formatter check109files passed; compilation
of `src` and `app.py` and Git whitespace checks passed. Independent review confirmed both
findings resolved. The original393 baseline tests remain unchanged. Credentials,
databases, backups, acceptance launcher and screenshots remain local/ignored;
only matching source, matching regressions and this report are intended changes.
Final private scans found zero configured-secret matches in intended Git files or
the isolated database and no persisted authentication-token fields. Index empty;
feature HEAD, original clean main and v1/v2/v3 tag objects remained unchanged.

Remaining live limits: selected catalog/variant/stock data was fresh cached evidence,
not newly requested in this acceptance; stock may change. Country-only freight,
delivery estimates, supplier listing claims and sample quality are not guarantees.
Included adapter, certification, food-contact safety, tracking, complete import
costs, profitability, genuine demand and account-specific rate/quota behavior were
not verified. DataForSEO remains unavailable and fixture-verified only. No orders,
payment endpoints, commits, pushes, merges, tags or deployment occurred in this
acceptance. The temporary8504 server was stopped after verification; user servers
were left running.

## 12. Focused score-scale and limit-status corrections — 2026-10-07

The user requested an explicit0–10 supply score. The implementation used0–10
raw dimensions but scaled aggregate/contributions to0–100, and omitted aggregate
scale labels. Supply UI now shows **7.75 / 10**, raw total **7.75 / 10**, and
contributions labeled **/10** for the live observation snapshot above. Evidence
coverage remains **85%**. market-v4 labels its distinct **/100** aggregate and
contributions; raw dimensions remain **/10**. Stored supply77.5/100, score weights,
recommendation thresholds, financial values and all V1/V2/V3 records are unchanged.
No scoring-version or database migration is required for presentation unit conversion.

Transport now uses **BUDGET_EXHAUSTED** with **LOCAL_REQUEST_BUDGET** or
**LOCAL_TIME_BUDGET** only for local request-count/time constraints. UI labels these
as local budget exhaustion. CJ HTTP429 uses **RATE_LIMITED / PROVIDER_RATE_LIMIT**;
CJ rate/quota codes use **RATE_LIMITED / PROVIDER_QUOTA_LIMIT**. A genuine429 remains
RATE_LIMITED when a retry cannot fit; **retry_blocked_by** records the local constraint
separately. These fields pass through sanitized provider outcomes into caches,
report stages and persisted per-action telemetry. Counts, caps and cooldowns unchanged.

Known historical CJ notices are interpreted read-only in both stage labels and
displayed telemetry. The old generic budget notice does not distinguish count from
time, so its source is **LOCAL_ACTION_BUDGET** rather than an invented specific
cause; the manual action's twelve actual dispatches establish its request-cap
exhaustion separately. Unknown historical origins remain explicitly unavailable.
Immutable action records and old reports are not rewritten by navigation.

Regressions first reproduced the unlabeled/wrong display scale and local-limit
misclassification. Checks cover displayed7.75/10 and hand-derived contributions,
unchanged stored aggregates, market /100 labels, count/time caps with no extra
dispatch, actual429 with a blocked retry, provider quota codes, old telemetry
display without database writes, and real transport/provider-to-persistence origin
propagation across restart. Rate/quota scenarios use HTTP-boundary fixtures;
**they are not live rate-limit verification**. No new CJ, OpenAI or DataForSEO
requests are needed or authorized by navigation during these corrections.

Final full suite for these corrections: **676 passed, zero failed/skipped**,
66.75seconds, using the original Python environment and a unique ignored absolute
artifacts/pytest-score-limit-final-UUID --basetemp. This includes the668 previously
passing cases and eight added presentation/legacy/persisted-origin cases.

Final lint, formatting (109files), compilation and Git whitespace checks passed.
Independent read-only review found no material issues; it separately exercised
legacy notice/immutability cases, old/new optional-field loading, blocked429 retries
under both count/time limits and both display scales. No reviewer provider calls.
Actual Streamlit on the same isolated database showed7.75/10,85% coverage and
financial revision4 in Demo Mode. Known subtotal/provenance remained unchanged;
navigation action payload digest remained7a52ad78eb6838121a1667225ff1d2092daf5fb8569c38154f63c73cf0d5be0b.
Dispatch counts remained auth1/stock2/shipping1; **zero new provider requests**.
Updated proof:
`C:/Users/Användar/.codex/visualizations/2026/10/06/01a110bf-ffe6-70a3-a95f-b7f446a369be/v4-cj-score-scale.jpg`.
The temporary server was stopped after the read-only UI check.

All changes remain uncommitted on feat/real-demand-supplier-v4. The earlier matching
fixes and live report were preserved. The final diff contains six source modules,
four test modules and four V4 documents; no new tracked/local artifact files.
Private configured-secret scan found zero matches in intended Git files; ignored
credentials/databases/backups/acceptance artifacts remain excluded. Index empty;
HEAD, original main and v1/v2/v3 tags unchanged. No push, merge, tag or deployment.

## 13. Earlier blocked DataForSEO live attempt — 2026-10-08 Europe/Stockholm

Starting branch feat/real-demand-supplier-v4, HEAD
20e68ea141e6857fd7ed89605e19b5995c382a3c, clean Git tree; previous full validation
676passing tests. Missing empty DATAFORSEO_LOGIN/PASSWORD placeholders were added
only to the ignored V4.env, preserving all existing bytes and credential values.
The user then supplied API credentials locally. Presence checks and the dotenv
acceptance launcher confirmed both configured without printing either value.

### Official contract, pricing and spend boundary

The existing adapter uses HTTP Basic authentication and one POST to
`https://api.dataforseo.com/v3/keywords_data/dataforseo_trends/explore/live`, one
task containing one exact keyword. Official
[Explore pricing](https://dataforseo.com/pricing/keywords-data/dataforseo-trends-api-pricing)
is **USD0.0012/task**. The
[Live contract](https://docs.dataforseo.com/v3/keywords_data-dataforseo_trends-explore-live/)
returns results in that response; no retrieval GET is needed. No paid parameters,
subregion/demography or merged-data endpoint was used. Maximum accepted spend
**USD0.10**, maximum one paid measurement submission, no retries.

Before the measurement, one documented free
[account-info GET](https://docs.dataforseo.com/v3/appendix-user-data/)
confirmed authentication, sufficient balance and account Explore Live rates of
USD0.0012/request. It reported cost0. No account login, balance value, headers or
other private account fields were printed or saved. A public supported-location
CSV GET confirmed Sweden2752, SE, Country; the official
[locations documentation](https://docs.dataforseo.com/v3/keywords_data-dataforseo_trends-locations/)
links the 2026-09-01 CSV. No credits, billing or account settings were changed.

### Genuine request and precise blocking response

The actual V4 Streamlit UI ran on loopback8504 using the existing
`python -m dotenv -f .env run --no-override -- <same-python> <acceptance-launcher>`
method and original Python3.12 virtual environment. User servers8501/8503 were
preserved. A new ignored database
`artifacts/live-dataforseo-portable-blender-20261008.db` was copied consistently
from the earlier isolated genuine-CJ acceptance database; no user's saved database
was replaced or migrated. Original CJ observations/selection and financial revision4
were retained as existing evidence, not claimed as newly fetched CJ data.

Visible product/query **Portable Blender**, target **Sweden (2752)**, quantity1.
Only the existing **Refresh demand** button submitted the measurement. No full
product research, supplier refresh or OpenAI request occurred. Actual JSON task:
keywords[Portable Blender], location_code2752, typeweb,
date_from2025-10-07, date_to2026-10-06. The adapter uses UTC to choose the closed
preceding-year window; this attempt occurred at2026-10-07T22:12:30UTC, which is
2026-10-08 locally. Granularity is determined by returned provider bins; **none was
returned or observed in this blocked request**, so no weekly/daily value is claimed.

The acceptance-only transport delegated to real HTTP without fixtures or altered
responses, checked the exact endpoint/query/country/task count and reserved a
persistent one-dispatch ledger before sending. A second submission, including
after restart or uncertain completion, is prohibited by that ledger. It captured
only sanitized response fields in ignored local artifacts; credentials/authentication
headers were not captured. This harness is not a production-code modification.

Response: **HTTP403**, DataForSEO **status_code40104**, tasks_count0, tasks_error0,
provider-reported **cost USD0**. Exact sanitized status_message:
“Please verify your account before using the API. You can complete verification
in the user panel: https://app.dataforseo.com/ .” Official
[error40104](https://docs.dataforseo.com/v3/appendix/errors/)
requires account verification in the user panel. The free account GET accepting
credentials/balance did not establish that this measurement API was unlocked.
No repeat submission was made. This is an account-verification blocker, not an
observed funding failure, successful empty measurement or parsing defect.

### Saved state, local verification and remaining limits

The integration saved FAILED, demand.statusfailed, current_eligibleFalse,
retainedFalse, zero observations and trendINSUFFICIENT_DATA. No representative
numeric values, measured granularity, prior/recent averages or trend percentage
can be reported. The UI retained the label relative search-interest/popularity;
the failure was not interpreted as zero demand, monthly volume, sales or buyers.
Supply score stayed7.75/10, supply coverage85%, confidence low, financial revision4;
market-v4 stayed unavailable/provisional with15% coverage and low confidence.
No HIGH/STRONG claim or economics requirement was bypassed.

Normal demand-component orchestration reused the genuine FAILED snapshot within
its one-hour failure-cache TTL: cache_hits[demand], requests0, same exact query,
geography and dates. A strict no-network test transport guarded that local check;
it supplied no simulated response and recorded zero requests. This verifies the
live-failure cache, **not a successful measured-demand cache**. Existing fixtures
separately verify successful fresh-cache reuse, successful-empty versus failed
refresh, deterministic trend/missing-zero handling and lifecycle semantics.

Affected existing tests: **64passed**,0failed/skipped,6.14seconds:
`python -m pytest -q --tb=short tests/test_demand_trend.py tests/test_supply_demand.py
--basetemp <unique-ignored-absolute-artifacts-directory>`.
No implementation defect was demonstrated, so no production or test code changed;
the completed676-test full-suite evidence is retained, not misreported as a new run.

Telemetry: one free account-info API GET (cost0), one measurement POST (cost0),
zero retrievals/retries, zero new CJ/OpenAI/page calls. The public location CSV GET
was an uncredentialed documentation check, separate from paid provider telemetry.
The app's explicit refresh recorded dataforseo_trends1/cache_hits[]; the local
failure-cache check recorded dataforseo_trends0/cache_hits[demand]. The isolated
database contains five actions including the three copied earlier-CJ actions.
Navigation/reopening and restart are checked against action payload digest
cf7035f5f783110458455f729cb5259b7626e096d1e531cafea270558451572e and the one-dispatch
ledger; no post-restart refresh is authorized in this acceptance run.

**DataForSEO remains fixture-verified only; live measured demand could not be
verified.** Authentication, pricing/funding preflight, a genuine blocked measurement
attempt and the failure lifecycle are distinct from live numeric-data verification.
Success/empty results, returned values/granularity, deterministic classification
from real values and successful measurement persistence/cache acceptance remain
pending account verification and a separately authorized bounded continuation.

Actual restart verification completed with the same dotenv launcher/database:
Saved Products reopened Portable Blender; Supplier Intelligence restored FAILED,
the exact query/country/date range/original observation time and INSUFFICIENT_DATA.
Default Demo Mode disabled Refresh demand and retained financial revision4.
Navigation, reopening and local scoring left five action payloads byte-equivalent
to the digest above and the live POST ledger at1. UI proof:
`C:/Users/Användar/.codex/visualizations/2026/10/06/01a110bf-ffe6-70a3-a95f-b7f446a369be/v4-dataforseo-account-blocker.jpg`.
The temporary8504 process was stopped; user servers8501/8503 were preserved.

Git whitespace check passed. Private configured-secret scans found zero matches
in intended Git files, the isolated database and sanitized response/dispatch
artifacts. .env, databases, backups, launcher and captures remain ignored. Only
this verification document is changed on the existing V4 branch; no commit, push,
merge, tag, deployment, commerce/order/payment or billing action occurred.

## 14. Authorized DataForSEO retry after account verification — 2026-10-08

The user completed account verification and explicitly authorized one new bounded
measurement, bypassing the cached40104 failure. The earlier records, response,
dispatch ledger and verification report were preserved. The same ignored isolated
database was reused with a new, separately named one-dispatch guard/capture and
the dotenv launcher on8504. User servers8501/8503 were preserved. **Only the
existing Refresh demand UI action** made a measurement request; force=True bypassed
the failure cache. No supplier/OpenAI/full-product research or automatic retry.

Official Explore Live pricing was checked again: USD0.0012/task. One additional
free account-info GET confirmed authentication, sufficient balance and the same
account rate before submission. No billing/account settings were changed. Current
acceptance spend ceiling USD0.10. The exact request was still Portable Blender,
Sweden2752, typeweb, dates2025-10-07 through2026-10-06. Its successful response was
collected at2026-10-07T22:33:19.086745Z (2026-10-08 00:33:19 Europe/Stockholm).

### Genuine returned series and deterministic interpretation

The real response reported HTTP200, overall/task status20000, one result with
type trends, exact keywords[Portable Blender], location2752, one matching graph,
and **provider-reported cost USD0.0012**. The existing parser validated request
echo/query/geography/ranges/relative-index values and stored52 observations as
SUCCESS/completed. No fixtures or altered provider responses supplied this data.

Returned span2025-10-12 through2026-10-06; the requested span remains retained
separately. Granularity: **51 seven-day bins plus one three-day ending bin**
(2026-10-04 through2026-10-06). The three nonmissing observations were:

- 2025-11-16–2025-11-22: **100**.
- 2025-12-21–2025-12-27: **76**.
- 2026-01-18–2026-01-24: **62**.

The other49 provider values were0, each stored with missing=True, consistent with
the documented meaning insufficient data. They are **not observed zero demand**.
Values are relative search-interest/popularity indices; they are not monthly
search volume, buyers, sales or independently validated demand. Provider/query/
Sweden/date ranges/bin granularities/normalization-series ID/original collection
time/source endpoint were retained; values were not broadened or translated.

Deterministic trend: **INSUFFICIENT_DATA**, reason “Periods are not uniform valid
intervals.” The documented V3 arithmetic requires uniformly sampled equal windows
and adequate nonmissing coverage; the three-day tail makes intervals nonuniform.
The series is also extremely sparse, with no usable recent-window observations.
No bins were trimmed, zeros converted to usable values or growth/decline invented
to improve the report. Prior/recent means and change_percent remain null. This
is the documented conservative calculation, not an observed implementation defect.
current_eligibleTrue means the successful raw observations are compatible/fresh;
it does not certify that there is enough data for a numerical trend.

### Scoring, cache and preserved records

Actual UI showed relative search-interest/popularity, SUCCESS/current raw-data
eligibility and INSUFFICIENT_DATA trend. Supply remained **7.75/10**,85% coverage,
low confidence and INSUFFICIENT EVIDENCE, with financial revision4 preserved.
market-v4 remained unavailable/provisional,15% coverage,low confidence and
INSUFFICIENT EVIDENCE; Numeric trend stayed null. This isolated saved product has
no compatible market-v3 report context, and the live trend is insufficient, so
the overlay cannot claim an independently measured opportunity score. Complete
economics, independent market evidence and other confidence gates were not bypassed.
No HIGH confidence or STRONG CANDIDATE was claimed.

Normal demand-component orchestration reused the genuine SUCCESS cache with
force=False: dataforseo_trends0, cache_hits[demand], all52 observations and the
original timestamp byte-equivalent. A strict no-network transport guarded that
local check and supplied no fixture response. This verifies successful live-cache
reuse without rerunning full product research. Both the original failed/cache-hit
actions and the new success/cache-hit actions remain immutable history. The first
five action payloads still match the previous attempt digest; seven actions total
after this success/cache check. Navigation/restart baseline digest:
0f94b9f3fe04d4e6bc19ba5cc87affdbe655a7b0d39b855e74310300573d7b7b.

Current retry telemetry: **one measurement POST**, zero retrievals/retries,
one free account-info GET(cost0), actual measurement costUSD0.0012, no new
CJ/OpenAI/page requests. The UI submission recorded dataforseo_trends1/cache_hits[];
the success-cache check recorded0/cache_hits[demand]. This run's consumed ledger
prohibits any second submission, including after restart. The earlier blocked
POST remains separately recorded at cost0; both attempts together still costUSD0.0012.

Affected existing parsing/trend/lifecycle/scoring tests: **83passed**,0failed/skipped,
5.86seconds. No production/test code changed; previous full676-test validation
is retained, not described as a new full-suite run. Successful-empty and synthetic
failure-refresh cases remain fixture verification; this live response is SUCCESS
with sparse observations, not SUCCESS_EMPTY.

**Live raw DataForSEO measurement is now verified for this exact query/geography.**
The earlier account-verification blocker is resolved. A usable numeric trend,
absolute market demand, positive profitability and a strong opportunity remain
unverified/unsupported by this sparse result. No further paid request was made.

Actual server restart with the same dotenv launcher/database restored all52
observations, original collection time, SUCCESS eligibility and INSUFFICIENT_DATA
trend in Saved Products/Supplier Intelligence. Default Demo Mode disabled Refresh
demand while showing genuine retained data. Seven action payloads remained
byte-equivalent to the baseline digest above; the new ledger remained one POST.
Original five action payloads, failed-response capture and consumed original guard
were preserved. UI proof:
`C:/Users/Användar/.codex/visualizations/2026/10/06/01a110bf-ffe6-70a3-a95f-b7f446a369be/v4-dataforseo-live-series.jpg`.
The temporary8504 process was stopped after verification; user servers8501/8503
were left running. No new CJ/OpenAI research occurred.

Whitespace check passed; private configured-secret scans found zero matches in
intended Git files, the isolated database or sanitized response capture. Only
docs/verification-v4.md is modified; credentials, acceptance scripts, database,
guard ledgers, captures and screenshots remain local/ignored. Feature HEAD/main/
release tags unchanged. No commit, push, merge, tag, deployment, orders/payments,
credits purchase or billing change occurred during this retry.
