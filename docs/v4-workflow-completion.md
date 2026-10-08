# Supplier workflow completion — 8 October 2026

> Historical first-fix verification below predates the genuine live freight acceptance
> and user cost adoption. Current status, limitations and daily-use validation are
> documented in [v4-daily-readiness.md](v4-daily-readiness.md).

Work remains uncommitted on `codex/v4-supplier-requirements-fix`, based on
`b34e5fc7a520f72d302d65a3a1b5bf9984ac11c7`. This supersedes the first debugging
pass's description-only requirements input and unchanged-startup instructions.

## Running app and root causes

The configured user app was port 8502, PID 18632, in this checkout, with
DATABASE_PATH=data/commerce.db and CJ/DataForSEO credentials present. Port 8501,
PID 24360, used the same checkout without optional provider credentials initially.
Neither process was stopped. The first fix's editor was visible for the exact
saved product d5837e9c897625ce12a88c88; no color requirement or selection had been
saved in the authoritative database. The previous test's Black requirement existed
only in its isolated database.

Port 8502 retained old imported modules. After this follow-up's code changes, a
browser reload exposed ImportError for configure_provider_environment: new app.py
was executing against cached old src.config. Reloading the browser did not refresh
the Python dependency graph. To preserve both user servers, a fresh process was
started on an unused port instead of restarting them or manipulating module state.

**The fixed app is http://127.0.0.1:8503, PID 15696**, using this checkout and
`C:/Users/Användar/Documents/ChatGPT/ai-commerce-agent/data/commerce.db`. App runtime
and Supplier Intelligence show revision `structured-supplier-workflow-v2`.
It is left running and open on the original saved laptop stand; no color was chosen.
The old 8501/8502 processes remain running. Use 8503 for the completed workflow.

CJ already parsed Black correctly. The target was unspecified. The approved V4
contract says option confirmation cannot supply missing decisive attributes; this
remains enforced. Missing target preference and missing supplier evidence are now
explained separately. Required supplier color has a structured input next to the
offers and in Data & assumptions. Explicit save/recheck stores product-scoped
preferences as requirements:<product_id> in existing V4 settings, without editing
the product description, changing demand identity, calling providers or migrating
the schema. Cross-tab fields synchronize to the saved preference and show the exact
product ID. The advanced description editor remains available for other attributes.

Phone side-mount holders remain NO_MATCH as laptop support stands even when colors
match. LIKELY_MATCH retains its exact-offer observed-attribute confirmation. Selection
stores immutable product/variant/warehouse observations and confirmation explicitly.
No Black preference, selection, cost or compatibility override is inferred.

## Freight and demand corrections

Freight previously required users to discover that quotes were new offer snapshots
and reselect them in the catalog. It also made unchanged supplier prices historical
when only freight changed. The dedicated shipping-method chooser now explicitly
binds the chosen quote to the selected immutable candidate/variant/stock cohort.
Select shipping quote preserves independent product-cost adoption; supplier and
freight adoption remain separate actions.

A pure pre-dispatch gate explains selection/configuration/identity/requirements/
freshness/warehouse blockers. Local cached quote selection works without live
configuration. Shipping distinguishes not requested, blocked, failed, empty and
successful. Malformed quote records remain FAILED and retain previous quote history,
instead of being labeled empty and clearing it. Candidate identity is aligned between
gate and lookup. CJ and factory stock remain distinct. Research links are labeled
as research context, not confirmed selectable CJ catalog offers. Scoring gates remain.

The actual V3 demand run made one DataForSEO request at 14:20:22 UTC, recording failure
around 14:20:42 UTC. Its adapter discarded the distinction between timeout, HTTP,
transport and validation errors and saved only a generic access notice. No numeric
status or raw failure log/response was retained. The 20-second duration is consistent
with the configured timeout, but does not prove the cause. Credentials were configured;
this was not a recorded local budget rejection or successful empty response.

The later V4 action reused the failed cache with zero requests and retained 52 older
bins, only 3 nonmissing. The UI shows UNKNOWN HISTORICAL failure, cache/request count
and 3/52 coverage. Failure/sparse values are not zero demand and produce no inferred
trend score. Future failures preserve only allowlisted categories and numeric HTTP/task
status: configuration, timeout, HTTP/provider rejection, transport or invalid response.
Safe notices propagate through the service; exception messages, response bodies and
credentials are not displayed or stored. No demand request was made during this work.

## Startup and verification

Normal launch now reliably loads absent optional provider variables:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8503
```

Choose an unused port for a new process. app.py loads only absent CJ_API_KEY,
DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD from .env. Existing process values, including
explicitly empty values, always win. OpenAI's existing settings precedence remains.
Startup performs no provider requests; scripts/start.ps1 uses the same entrypoint.
The explicit dotenv --no-override wrapper remains valid when loading the whole dotenv
environment is desired, but is no longer required. Launch regressions use synthetic
temporary dotenv files; AppTest never loads the user's real credentials.

Final suite: **699 passed**. Ruff lint/format and Git whitespace checks passed.
Regressions failed before structured UI/diagnostic/launch fixes, candidate lookup
alignment, configuration dispatch gate and malformed-quote lifecycle correction.
Code review findings were resolved. Existing tests and scoring safeguards remain intact.

Actual browser verification on port 8518 used a SQLite backup of the original saved
data, with external HTTP dispatch prohibited. It exercised structured Black save,
local recheck, exact variant/warehouse selection, explicit USD 3.10 product-cost
adoption, freight refresh through the real CJ parsing adapter, explicit quote selection,
separate freight adoption and process restart. Requirement, selection and both adopted
values/provenance persisted after restart.

Catalog, stock and demand are captured normalized observations with original times.
No captured live freight quote existed. Freight replays the repository's **synthetic
contract response**, USD 12.00, 2–5 days, tracking unknown. The isolated app labels it
OFFLINE REPLAY; it is not a real Swedish price or delivery promise. Its known-cost
subtotal was USD 15.10, while missing duty/customs/packaging/handling/fees/returns/ad
assumptions left full economics unavailable. No zero assumptions or scores were invented.

SHA-256 confirmed the original database and .env unchanged. The original description
still lacks color, and its selection, V4 financial and structured requirements record
counts remain zero. Only the replay server is stopped after verification. The new
real app on 8503 is left running. No orders, payments, commits, pushes, merges, tags
or deployments occurred.

## Remaining choice and live acceptance

The user must declare the intended color; do not enter Black solely to satisfy a gate.
Full profit requires truthful missing cost assumptions, and market scoring needs
adequate current demand evidence.

After a valid explicit selection, the remaining live freight acceptance is CJ
POST /api2.0/v1/logistic/freightCalculate, for vid
1CC71DF3-9C07-43FD-9B78-074266306AD0, quantity 1, CN → SE, storageIdList
["{6709CCD7-0DC7-43B1-B310-17AB499E9B0A}"]. Authentication/token refresh may be
required first. No catalog, OpenAI or paid DataForSEO call is needed while the saved
variant/stock remain fresh. Quoting commits no order or shipping payment; any API
fee is not established by repository/account evidence, so no dollar-fee guarantee
is made. This live request was not performed and requires explicit authorization.

Changed files: app.py, src/config.py, src/database/supply_repository.py,
src/research/providers/demand_trend.py, src/supply/{models,matching,service,demand}.py,
src/ui/{dashboard,products,research_details,supplier_intelligence}.py, new
src/ui/supplier_requirements.py and supplier_shipping.py, README and diagnosis/plan
documentation, tests/conftest.py, new test_provider_launch.py/test_supply_workflow.py,
and freight/sparse-demand fixtures. Earlier uncommitted requirements tests and fixture
are preserved. Ignored replay artifacts/screenshots remain under artifacts/.
