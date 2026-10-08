# Daily research reliability implementation plan

> Execute inline using superpowers:executing-plans; obtain one independent read-only review before delivery. Leave all work uncommitted.

**Goal:** Make existing V4 research, comparison and economics usable under explicit assumptions, with honest unknowns and no new provider calls.

**Design:** Keep V1/V2/V3 models and arithmetic unchanged. Extend the V4 financial JSON snapshot with optional tax assumptions and recorded manual price conversion. Old JSON remains readable and immutable history remains untouched; missing new assumptions limit current V4 calculations. Keep provider observations immutable. Build read-only comparison/export from the same current eligibility and calculations shown in details.

**Constraints:** Current codex/v4-supplier-requirements-fix branch; preserve all existing work, .env, original database and servers. No new live calls, orders, payments, commits or deployment. Use an isolated copy for UI testing, then update the existing 8503 process once if imports require it; leave no extra app instance. User explicitly authorizes routine fixes and execution, overriding skill approval/commit stages.

## Tasks

- [x] 1. Write and run failing financial regressions: unspecified tax must not produce complete profit; VAT-inclusive/exclusive price, unrecoverable/partially recoverable import VAT, gross customer payment fees, quantity >1 fixed fees/ads/returns, explicit zero, FX provenance and old-record round trips. Implement src/supply/financial_scenario.py and extend src/supply/economics.py without changing V3. Adapt complete V4 fixture scenarios to explicitly declare tax assumptions; keep historical V3 pinned assertions.
- [x] 2. Write failing UI/export regressions. Add explicit tax/FX forms, meaningful field help and result-specific missing inputs. Show quote fee fields and delivery limits, restore saved shipping-method choice on reopen and distinguish stale freight. Add read-only V4 product comparison and JSON evidence export with assumptions, unknowns, timestamps, current eligibility and scoring gates. No calls on navigation/recalculation/export.
- [x] 3. Verify 4 varied workflows with captured stand/live freight and labeled synthetic cases (heated lunch-box voltage conflict, phone holder wrong identity, pet-remover missing stock/freight), sparse/failed demand, cache reuse and dependency invalidation. Exercise real Streamlit UI on isolated DB through save/recheck/select/quote/adopt/economics/export and one restart.
- [x] 4. Independent read-only review; fix material findings with failing regressions. Run full suite, Ruff lint/format, compilation, whitespace and secret checks. Update readiness/startup docs, verify original DB/.env hashes and server inventory, deliver exact URL and reviewable intended diff.

## Review focus

VAT basis must never be silently chosen. FX must retain rate/date/source and not masquerade as provider evidence. Payment fees apply to the charged customer amount, while revenue excludes output VAT. Import VAT must not be double-counted in other costs. Quantity scales units but fixed fees, return loss and ads remain per order. Saved quotes must reselect the saved method, and expiry must be visible without provider calls.

## Ledger

Initial investigation: branch/HEAD/main/tag verified at b34e5fc7; original saved stand has Black, exact variant/storage and live Eub quote, adopted costs; latest snapshot revision 9. User servers 8501/8502/8503 remain. Preservation hashes at artifacts/v4-daily-preservation.json. Baseline full suite started before changes.

Ruling: Do not compute tax liability, choose VAT rates, infer recoverability or infer FX. Model user-entered amounts and rates; limit special tax schemes, separate customer delivery charges, multiple currencies inside one cost ledger, overhead and income tax explicitly. If wrong, user scenarios need additional inputs rather than a silently overstated profit.

Tasks 1–4 complete, uncommitted: financial regressions RED→GREEN, presentation/save/legacy migration regressions RED→GREEN; exact freight-total and price-unit review findings RED→GREEN. Final full suite 723 passed; all quality checks passed. Read-only independent review found no other material issues. Varied captured/synthetic workflows plus real isolated browser save/restart/download acceptance passed. Original DB/.env hashes unchanged. Final user app 8503 PID16340; 8502 preserved, 8518 stopped. No new live provider calls. No deferred reviewer findings.
