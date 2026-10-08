# V4 daily research and comparison

Current fixes remain uncommitted on `codex/v4-supplier-requirements-fix`, based on
released `main` / `v4.0.0` commit `b34e5fc7a520f72d302d65a3a1b5bf9984ac11c7`.
The original database, credentials and other user servers are preserved.

## Root causes and final behavior

The original color ambiguity came from an undeclared target preference, combined
with no structured color editor. Supplier `variant_key: Black` is normalized, but
does not declare the user's intended color. Saved structured requirements now
recheck locally for the exact displayed product. Contradictory colors and the phone
side-mount accessory remain rejected. A shortlist records a role, notes and an
observation snapshot; it neither selects an offer nor adopts costs.

Freight previously lacked a practical saved-method chooser. It now has explicit
request/method/selection stages, restores the saved method, and shows not-requested,
blocked, failed, empty, stale and successful states. One card represents each exact
variant/warehouse snapshot; multiple freight methods appear in the method chooser.
Factory stock and CJ stock remain distinct. Delivery and tracking are unknown when
not returned. Optional CJ taxes, clearance and total-postage fields are displayed
separately; the approved provider contract adopts `logisticPrice`, without silently
adding other fee fields. Review any difference before entering extra costs.

V4 previously did not represent selling-price VAT basis/import VAT and treated the
selling price and unit costs as one-unit order amounts. It now requires an explicit
price basis (including VAT, excluding VAT, or explicit no-output-VAT scenario), a
user-entered rate when applicable, import VAT/unit and recoverability when positive.
No business tax setup, rate, recovery or zero is inferred. Recoverable import VAT
is excluded from modeled cost, though it may require cash funding. This is scenario
arithmetic, not tax advice or a determination of obligations.
The [European Commission's VAT deduction guidance](https://taxation-customs.ec.europa.eu/archives/taxable-persons/deductions_en)
describes eligibility, partial deduction and documentary conditions for imported goods;
these are why recovery cannot be inferred from destination alone (checked 2026-10-08).

Landed cost is per unit. Revenue excludes output VAT; percentage payment fees use
the total charged customer amount including VAT. Fixed fees, expected return loss
and advertising are per order; units scale unit revenue and costs. Net profit is
estimated contribution after ads, before overhead and income tax. Break-even CPA
is contribution before ads, per order. Adopted freight retains its exact quote
total for order calculations, correcting rounding when dividing by quantity.
Returned-order loss is incremental relative to normal order economics; exclude
costs already charged elsewhere and account for refunds/recovery consistently.

Manual FX records source price/currency, USD per source unit, rate date and public
source or explicit estimate. Changing USD price removes the old conversion link.
There is no automatic exchange-rate lookup. Financial records gain optional JSON
fields without a database schema migration. Legacy records remain readable; missing
tax assumptions block applicable results. Legacy selling-price provenance units
are normalized in the read model with an explanation; stored history is untouched.
V1/V2/V3 arithmetic, stored scores and meanings remain unchanged.

Saved-product comparison and JSON export use the same current compatibility,
freshness and scoring gates as details. Exports include native observation currency,
identities, timestamps, saved requirements, selection, shortlist, tax/FX assumptions,
adoption provenance, unknowns, demand status and score reasons. Navigation, export,
recheck and financial saves dispatch no provider requests.

## Evidence and remaining limits

The previously authorized live freight call on 2026-10-08 returned 20 methods.
The user's selected CJPacket Eub Special Line costs USD13.60 for one unit, estimated
8–12 days, tracking unknown, captured at 15:40:45.753336 UTC. Supplier price USD3.10
was collected at 14:21:38.848678 UTC. These are genuine earlier live observations;
this daily-use work performs **zero new provider calls**. The earlier USD12.00,
2–5-day quote was synthetic and remains a separate contract fixture. The new capture
fixture preserves exact genuine variant/stock/quote identities and timestamps;
replaying it is not a new live quote.

Latest saved DataForSEO failure is shown separately from retained historical sparse
observations. Failures without detailed telemetry retain an unknown cause. New
failures retain only sanitized category/status information. Relative interest is
not sales or search volume. Sparse/nonuniform data cannot establish a trend; missing
observations and failed refreshes do not become zero demand. Evidence gates remain.

Country-only freight is supported; no personal-address/postcode quoting or orders.
Special VAT schemes, separate customer delivery charges, multiple currencies within
one cost ledger, overhead and income tax are outside this scenario model. No supplier
quality, delivery, demand or profit is guaranteed. Freshness still expires: freight
and stock 6 hours, supplier price 24 hours, demand 7 days. Refresh only the needed
component explicitly after resolving a shown issue.

## Minimal use and launch

Final user URL: `http://127.0.0.1:8503/`. In Saved Products, choose the product and
open Supplier Intelligence. The original stand already has the user's Black choice,
exact selected variant/warehouse, Eub method and both explicitly adopted costs.
Do not repeat research to populate tax assumptions. Declare the remaining applicable
tax scenario, then Save V4 tax assumptions. Blank inputs remain unknown; enter zero
only when it is your intended estimate. Enter USD price directly or use manual FX.
Open V4 comparison and evidence export above details to compare/export saved products.

Normal launch from the repository (use a free port when another process is running):

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8503 --browser.gatherUsageStats false
```

Startup loads only missing CJ/DataForSEO variables from `.env`; existing process
values, including empty values, win. OpenAI uses existing settings precedence.
The reliable whole-dotenv alternative also preserves existing environment values:

```powershell
.\.venv\Scripts\python.exe -m dotenv -f .env run --no-override -- .\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8503 --browser.gatherUsageStats false
```

No providers run at startup. Provider configuration alone does not prove connectivity.

## Acceptance

Final app: **http://127.0.0.1:8503/**, PID **16340**, same checkout and original
`data/commerce.db`. Updated once after acceptance. Port 8502 PID18632 was untouched;
8501 was already not listening at final inventory. Temporary port8518 was stopped.

Final full suite: **723 passed in 70.83 seconds**. Ruff lint passed, format check:
102 files formatted; compilation and Git whitespace checks passed. A credential
scan of all 39 intended changed/new source/document/test files found no real configured
credential values. SHA-256 verified original database and `.env` unchanged before
and after the final app update. No commits or other Git publishing actions.

Real browser acceptance on an isolated SQLite backup exercised structured Black
save/local recheck, exact variant/warehouse selection, separate supplier adoption,
captured genuine freight replay, Eub selection, separate freight adoption, explicit
cost/tax saves, manual FX save, process restart, reopening and downloading the JSON
export from the UI. Export contained four products and retained the exact saved
choices, provenance and failed demand status. No provider dispatches; network was
prohibited. Recorded illustrative assumptions: VAT-inclusive price, output VAT25%,
import VAT0, and manual349SEK ×0.1USD/SEK dated2026-10-08 from an explicitly labeled
test estimate. After restart: USD16.70/unit landed, USD8.55/order net contribution,
USD9.55/order CPA. These assumptions exist only in the disposable copy, not the
user database. Screenshot: ignored `artifacts/v4-daily-restart-economics.png`.

The meaningful scenarios cover genuine captured Black stand, conflicting grey color,
wrong phone-holder identity, synthetic electrically incompatible lunch box and
synthetic pet remover with missing stock/freight. Captured sparse/failed demand is
tested separately. Network is prohibited for the isolated real-browser workflow.
Independent read-only review identified freight rounding and selling-price unit
metadata; both have failing-before-fix regressions and were corrected.

## Intended complete branch diff

Includes preserved earlier fix work and the current daily-use changes; leave all uncommitted. Ignored copies, screenshots, telemetry, credentials, databases and downloaded exports are excluded. Review patch: ignored `artifacts/v4-daily-review.patch`.

- `README.md`
- `app.py`
- `docs/superpowers/plans/2026-10-08-daily-research.md`
- `docs/superpowers/plans/2026-10-08-supplier-workflow.md`
- `docs/v4-daily-readiness.md`
- `docs/v4-supplier-selection-fix.md`
- `docs/v4-workflow-completion.md`
- `src/config.py`
- `src/database/supply_repository.py`
- `src/research/providers/demand_trend.py`
- `src/supply/comparison.py`
- `src/supply/demand.py`
- `src/supply/economics.py`
- `src/supply/financial_scenario.py`
- `src/supply/matching.py`
- `src/supply/models.py`
- `src/supply/service.py`
- `src/ui/dashboard.py`
- `src/ui/products.py`
- `src/ui/research_details.py`
- `src/ui/supplier_comparison.py`
- `src/ui/supplier_financial.py`
- `src/ui/supplier_intelligence.py`
- `src/ui/supplier_requirements.py`
- `src/ui/supplier_shipping.py`
- `tests/conftest.py`
- `tests/fixtures/v4_captured_live_freight.json`
- `tests/fixtures/v4_freight_contract_response.json`
- `tests/fixtures/v4_laptop_stand.json`
- `tests/fixtures/v4_sparse_demand_snapshot.json`
- `tests/test_provider_launch.py`
- `tests/test_supply_app.py`
- `tests/test_supply_economics.py`
- `tests/test_supply_requirements.py`
- `tests/test_supply_scoring.py`
- `tests/test_supply_workflow.py`
- `tests/test_v4_daily_presentation.py`
- `tests/test_v4_financial_scenario.py`
- `tests/test_v4_varied_workflows.py`
