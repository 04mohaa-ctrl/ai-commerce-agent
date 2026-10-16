# V5 discovery and comparison implementation plan

Goal: discover supplier candidates, preserve exact supplier identity, research deliberately,
and compare 3–5 scenarios using V4 evidence and financial gates. Local single-operator
architecture remains explicit; this release does not claim shared-user isolation.

Baseline: verified local main 124c1f741aa584cf6c2444b52407992863a754f4.
Existing checkout and servers are preserved. Work occurs on codex/v5-discovery-comparison.
The initial implementation scope prohibited commits, live provider calls, purchasing,
publishing and deployment. Later user instructions separately authorized the bounded
[catalog acceptance](v5-live-acceptance-20261016.md) and feature-branch commit/push.
Merging, tagging, deployment and new provider calls remain outside the publication scope.

## Tasks

- [x] Discovery: add separately validated catalog observations (avoid changing V4 immutable
  observation hashes), documented listV2 filters, bounded pages, account-compatible caches,
  stable CJ identity mapping and explicit local saves. Test duplicates, partial/empty/failure,
  malformed prices/links, filter validation and zero dispatch on navigation.
- [x] Candidate research: reuse SupplierIntelligenceService, pin supplier searches to saved
  CJ identity, preserve variant IDs, use existing selection/freight/adoption controls.
  Test wrong product/accessory/conflicting variants and preservation after failures.
- [x] Demand query review: save original and chosen Swedish/English terms separately;
  exact-query V4 caches and observations; no automatic translations or index addition.
  Test query isolation, sparse/stale evidence and bounded batch actions.
- [x] Compare: persist group membership and decision notes; enrich V4 comparison export
  with scenario compatibility, missing inputs, next actions and separate demand series.
  Test quantity/country/currency/tax/FX mismatches, unknowns and restart/export behavior.
- [x] Beta preparation: loopback-only startup, explicit offline mode, backup/restore/export/
  deletion tooling and tests, readiness checklist with code evidence and effort estimates.
  Test actual browser flow using an isolated synthetic fixture database.
- [x] Validate: full pytest, ruff lint/format, compile, independent read-only review, final
  diff and local URL. Record evidence classes and remaining launch blockers.

## Decisions

Use additive V5 tables with an explicit schema-5 marker and verified pre-V5 SQLite backup.
V5 reads V1–V4 data; V4 rollback uses the matching pre-V5 backup at a new path. Old
readers must reject schema 5 rather than partly read supplier-identity snapshots.
Do not modify SupplierProductCandidate's fields: observation IDs bind every field.
Use existing CJ routes only. Verify listV2 parameter/price semantics in official docs.
No multi-product supplier/web batch: per-candidate explicit research makes request scope
clear. Demand batch is capped at five exact queries, one request each, with a deadline
and durable per-query success. Uncertain paid submissions are never automatically retried.
Shared hosting/auth/credential ownership require an operator decision; finish local work
and describe concrete deployment options instead of adding a cosmetic login.

## Progress and evidence

Initial sandbox test run could not write inside the native worktree; interrupted. Rerun
with authorized worktree access, rather than interpreting environment errors as regressions.

Verified baseline: 723 tests passed in 102.47 seconds using a new artifacts temp directory.
Discovery, query review, groups, comparison, offline mode, recovery and local binding
guards are implemented. New behavior has offline unit/integration/AppTest coverage.
Independent read-only review found group-editor state retention, partial candidate saves,
demand total-deadline enforcement, misleading currency labels and V4 rollback ambiguity.
Each material issue has a reproducing regression and a fix. Catalog nonce cache reuse
across process restarts remains deliberately conservative and documented.

Routine decisions: keep additional demand terms exploratory so V4 score semantics do
not change; do not invent translations or catalog URLs. Keep a single operator per app
instead of adding authentication without record ownership. The next launch decision is
local tester installations versus isolated hosted instances versus a shared service.

Initial browser acceptance used a new synthetic database, not existing operator data.
The later approved catalog acceptance used another isolated database and three genuine
candidates; variants, stock, freight, demand and economics were not fetched or established.
The final offline suite passed 770 tests. See v5-readiness.md and verification-v5.md for
the evidence boundaries and remaining launch requirements.
