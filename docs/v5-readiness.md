# V5 launch readiness — updated 16 October 2026

## Verdicts

- **Local use: suitable for a trusted single operator**, subject to the documented provider
  and evidence limitations. Offline acceptance is available without keys. The approved
  keyword/page catalog acceptance passed; optional filters remain contract/fixture verified.
- **Hosted private beta: blocked.** Controlled local evaluation is available.
  Separate local installations with each tester's database and credentials are the smallest
  next step. Invitation-only access to one shared Streamlit server is not user isolation.
- **Public launch: not ready.** Authentication, ownership, spending controls, hosting,
  provider-use rights, privacy operations and production monitoring remain unresolved.

These are architecture and operational verdicts, not conclusions drawn from test counts.

## Code-backed checklist

- [x] Inspect existing architecture and baseline. Local `main` is
  `124c1f741aa584cf6c2444b52407992863a754f4`; baseline 723/723 passed. Existing checkout
  and its data are untouched. V5 lives in its own worktree and feature branch.
- [x] Explicit external actions. `src/ui/discovery.py` requests one page only on submission;
  the next-page button uses the last submitted filters. `DiscoverySearch` caps pages at 2,
  size at 10. CJ transport allowlists read-only research routes. No orders or payment routes.
- [x] Known cost versus unknown cost. Catalog observations stay outside financial inputs.
  V4 selection, freight and cost adoption stay explicit. Blank is unknown; zero is deliberate.
  `tests/test_v5_discovery.py`, existing supply/economics suites and browser acceptance cover this.
- [x] Consistent comparison. `src/discovery/comparison.py` reuses the V4 evidence document,
  checks geography, quantity, currency, tax and FX assumptions, and marks incomplete scenarios.
  Display labels identify scenario currency independently of observed supplier currency.
- [x] Query identity. `src/discovery/queries.py` stores reviewed terms per product and country.
  V4 demand snapshots retain exact query, geography, provider, period, timestamps and series.
  Separate normalized series are exported independently. Additional terms do not change V4 scores.
- [x] Bounded demand actions. Up to five chosen queries for one product; compatible caches
  reused; 120-second dispatch budget, at most five provider submissions, no automatic retries.
  DataForSEO uses the existing absolute-deadline transport with a 20-second request deadline
  and 2 MiB response limit. Partial progress is durable. The OS/network scheduler and local
  SQLite latency are not hard real-time guarantees. No multi-product paid batch is implemented.
- [x] Recovery preparation. `DiscoveryRepository.enable()` takes a verified pre-V5 backup,
  then transactionally activates schema 5. `src/database/maintenance.py` uses SQLite backup
  (including committed WAL), integrity checks, exclusive new targets and non-overwriting restore.
  Tests restore a separate database and check retained records/version. Candidate writes are atomic.
- [x] Reproducible local startup. Locked requirements already exist. `scripts/start-v5.ps1`
  chooses loopback, checks its port and defaults to offline mode with a separate V5 DB.
  `app.py` refuses a non-loopback server binding before loading credentials or opening data.
- [x] Generic browser errors and minimal developer toolbar. `.streamlit/config.toml` suppresses
  exception details in the browser. Existing provider errors omit raw response bodies and keys.
- [x] Process health. Streamlit's local `/_stcore/health` is available. This is a process
  liveness check, not a database restoration test or provider connectivity check.
- [x] Local export/deletion tooling. Full JSON export includes histories/caches; comparison
  export includes group decisions, assumptions and evidence. CLI deletion requires a backup,
  removes candidate records/referencing groups and clears caches. Tests retain unrelated products.
- [ ] Authentication/authorization. There is no login or access-control principal in
  `dashboard.py` or the repositories. Loopback is a local boundary, not authentication;
  tunnels/proxies must not expose this app as a shared service.
- [ ] Per-user ownership. `ProductRepository`, `SupplyRepository`, `MarketIntelligenceRepository`
  and `DiscoveryRepository` have no owner column. Queries, saved groups, histories and exports
  are global to one DB. No multi-user implementation or user-isolation claim is made.
- [ ] Per-user/daily spending quotas. Current caps apply to each explicit action, not a daily
  balance, user or account. Repeated actions can spend more. Hosted access needs atomic
  reservations, concurrent-action controls, durable usage ledgers and operator budget ceilings.
- [ ] Hosted secrets. Local credentials stay server-side in process environment or ignored
  `.env`; they are not entered in UI/DB. One process uses one operator's provider accounts.
  Shared hosting needs secret storage, rotation and a decision about who pays. Do not put
  multiple testers' keys into this environment or share an operator's account credentials.
- [ ] Production database/operations. SQLite fits the local low-write workflow. Shared service
  needs a selected DB and migration strategy, concurrency/load tests, encrypted off-machine
  backups, scheduled restore drills, alerting, deployment health/readiness checks and incident response.
- [ ] Monitoring/log policy. No error-monitoring service, redaction integration, alert routing or
  log retention is configured. Generic browser errors do not sanitize arbitrary server logs.
- [ ] Privacy/retention. No automatic expiry or account lifecycle exists. Agree retention for
  research, caches, exports, logs and backups before invitations. Logical deletion is not secure
  disk erasure and backups intentionally retain pre-deletion data. Handle backup expiry and any
  downloaded exports as part of deletion requests; do not claim complete erasure from the CLI alone.
- [ ] Provider terms. Public documentation review is recorded below; applicable account/API
  permission to serve catalog content and images to testers still requires confirmation.
- [x] Bounded catalog acceptance. One approved authentication and one unfiltered keyword
  search returned ten records; three genuine candidates passed local save/duplicate/restart/
  compare/export checks. [Report](v5-live-acceptance-20261016.md). For these candidates,
  variants, stock, freight, delivery, measured demand and complete economics remain unverified.
  No new provider calls were made while preparing the feature-branch commit.

## Provider documentation and terms reviewed

The [official CJ product reference](https://developers.cjdropshipping.com/en/api/api2/api/product.html)
documents `listV2`, its keyword/country/category/price filters, `bigImage` and USD `sellPrice`.
V5 implements that subset and creates no listing URLs. The existing authentication,
variant, stock and freight allowlist stays intact. See also
[CJ limits](https://developers.cjdropshipping.com/en/api/start/limit.html).

The [CJ user agreement](https://cjdropshipping.com/user-agreement/en), sections III and XII,
restricts account sharing and assigns rights to catalog content. It is not sufficient evidence
of blanket redistribution permission. Confirm API/account permissions for the intended beta
and image use; do not give testers access to an operator's credentials.

[DataForSEO terms](https://dataforseo.com/terms-of-service), updated 12 June 2026, include
data-use restrictions and make duplicate task submissions the integrator's responsibility.
Confirm the intended end-user display/export use against the applicable agreement. No
automatic paid retry has been added. This review records dependencies; it is not a legal clearance.

## Concrete launch options and rough effort

Estimates assume one experienced Python engineer, 5–10 beta testers, existing V5 tests,
no ordering/payment scope and prompt access to deployment/provider decisions. Calendar time
for vendor permission, security review and tester feedback is additional. They are ranges,
not promises or completion percentages.

1. **Separate local installations, tester-provided keys (recommended first beta).** Each
   tester owns a machine, DB, exports and spending account. Smallest operational change;
   installation/support friction and no central monitoring. Roughly **1–3 engineering days**
   for packaging, setup/backup instructions and an invitation/feedback checklist, plus
   provider permission review and any additional acceptance scopes. The bounded catalog
   flow is complete; local evaluation is not a hosted private beta.
2. **One isolated hosted instance per tester.** Separate process/storage/secrets and an
   authenticated TLS gateway per instance. Easier onboarding; more hosting/backup overhead.
   Decide operator-funded keys with per-instance ceilings versus privately provisioned tester
   keys. Roughly **1–2 engineering weeks**, depending on the chosen host and gateway, then
   a restore/access-boundary test and terms/privacy review. No deployment has been made.
3. **Shared multi-user service.** Managed authentication plus owner-scoped repositories,
   authorization on every read/write/export/cache path, a production DB, migrations,
   quota reservations, a secret store, jobs, monitoring and privacy lifecycle. Best long-term
   UX; largest redesign. Roughly **4–8 engineering weeks** plus independent security review,
   load/restore testing and live acceptance. Public launch adds abuse controls, support and
   production operations; budget a further **2–4 weeks** under these assumptions.

The outstanding business decisions are hosting target and credential/funding ownership.
No services were bought, billing changed, invitations sent or deployments performed.

## Backup, rollback, export and retention commands

Run from this worktree with its dependencies. Substitute a deliberate database path. These
commands are tools for the operator; they were tested only against isolated test databases.
All output destinations must be new files and their parent directories must already exist.

```powershell
python -m src.database.maintenance backup data/v5-local.db backups/operator-snapshot.db
python -m src.database.maintenance restore backups/operator-snapshot.db data/restored-check.db
python -m src.database.maintenance export data/v5-local.db artifacts/operator-export.json
python -m src.database.maintenance delete-product data/v5-local.db EXACT_PRODUCT_ID --backup backups/before-delete.db
```

Before V4 rollback, preserve the V5 file and exports, restore the matching
`artifacts/v5-backups/before-v5-*.db` to a **new** path, verify records, and point V4 at that
restored schema-4 file. V4 must not open schema 5. Do not overwrite either DB. Merely
viewing a V4 product does not activate V5. Ordinary legacy product serialization omits
the new supplier field when absent; discovered candidates require V5's explicit identity.

## Optional live acceptance preparation

The [16 October acceptance preparation](v5-acceptance-20261016.md) now supplies a concrete
empty DB, offline preview, documented 50-point CJ scope and two-request/no-retry harness.
It supersedes the generic four-attempt preparation description below. The exact scope was
approved and [completed successfully](v5-live-acceptance-20261016.md). Hosted-beta readiness
remains a separate undertaking.

Live acceptance is not necessary to demonstrate local functionality, but is required before
claiming current provider connectivity or catalog/evidence quality. No live calls are queued.
Prepare an operator-approved exact keyword/filter/market/query list and a fresh isolated DB.
The smallest CJ discovery check is one `GET product/listV2` plus token acquisition if needed;
the local action cap is four HTTP attempts. Variant/stock/freight checks would be separate,
named actions bound to returned IDs. A demand check is one `POST .../explore/live` with one
reviewed keyword and closed dates. Monetary cost and CJ points must be verified against the
actual account before seeking approval; this release does not invent a cost estimate or
ask for permission to execute an unspecified live batch.
