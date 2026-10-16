# V5 acceptance preparation — 16 October 2026

**Historical preparation record.** The user approved this exact scope and the bounded
[V5 live acceptance completed successfully](v5-live-acceptance-20261016.md). The pending
statuses and empty-DB observations below describe the state before that approved capture.
At preparation time work was uncommitted on `codex/v5-discovery-comparison`, based on main
`124c1f741aa584cf6c2444b52407992863a754f4`. No hosted-beta work or deployment.

## Independent review and fixes

A separate read-only reviewer inspected the post-review changes, then checked the fixes.
Atomic candidate saving was sound: origin, candidate, saved result and destination use one
transaction and a second identity check under the write lock. Failure rollback is tested.

Additional findings were reproduced and fixed:

- Returning to Compare after Streamlit removes widget keys now reloads the saved group's
  name, members, decision and notes. Switching groups still loads the correct group.
- The shared absolute-deadline transport bounds DNS on a worker before connecting to a
  numeric address. TLS retains the original hostname. It covers demand and CJ socket/TLS
  operations; acceptance uses a 30-second action deadline and zero automatic retries.
- Schema activation now checks state under a SQLite write reservation before backup and
  migration. This includes the older schema-2/3/4 steps, preventing concurrent downgrades.
  Every retained pre-V5 snapshot must validate as schema 4. Restoring uses a new path.
- Acceptance export replay returns the existing immutable export before any DB writes.
  Replaying cannot reset an operator's later decision; changing the trio is rejected first.

The final reviewer confirmed the migration and replay fixes, with no remaining material
finding in that focused scope. Review/test data was isolated and synthetic, never user data.

Fresh full-suite result: **770 passed in 142.73 seconds** (previous V5 report: 759).
Ruff lint/format, compileall and `git diff --check` passed. HTTP/socket and external DNS
boundaries are blocked in the offline suite; provider responses use labeled fixtures.
Log: `artifacts/full-v5-acceptance-20261016.log`. Review patch including untracked V5 files:
`artifacts/v5-acceptance-preparation-20261016.patch`. Nothing was staged or committed during
this preparation; the later feature-branch publication was authorized separately.

## Three evidence classes

1. **Offline/synthetic:** full V5 tests, MockTransport contracts, AppTest navigation and fresh
   sessions. The existing browser demo at http://127.0.0.1:8510 uses `data/v5-acceptance.db`
   and labeled synthetic records. These validate behavior, not current supplier connectivity.
2. **Historical V4 live:** retained reports and labeled captures in
   [verification-v4.md](verification-v4.md) and [v4-daily-readiness.md](v4-daily-readiness.md).
   They include genuine CJ variant/stock/freight, explicit cost adoption, and a sparse
   DataForSEO Sweden series. Original observation times remain historical; none was refreshed
   or copied into the new acceptance DB. Historical successes do not establish today's API
   access, current prices/stock or V5 discovery behavior.
3. **New V5 live:** **not run**. No authentication, catalog, detail, stock, freight, demand,
   account or OpenAI request has been made during this preparation. Public documentation
   was read; no account data was requested.

## Prepared workspace

- Database: `data/v5-live-acceptance-20261016.db`, schema 5, **zero application records**.
  Migration metadata is the only initial content. No synthetic records or copied caches.
- Evidence directory: `artifacts/v5-live-acceptance-20261016/`; currently only `scope.json`
  and the offline preparation audit. There is no attempt marker or capture.
- Preview: **http://127.0.0.1:8511**, a separate loopback process using
  `scripts/v5_acceptance_app.py`, `COMMERCE_OFFLINE=1`, and the dedicated DB. The actual V5
  dashboard is reused with initial demo seeding and synthetic discovery examples disabled.
- Browser checked Dashboard → Discover → Candidates → Compare: zero products, disabled
  live search and a clear three-candidate requirement. AppTest separately checks the same
  UI after a labeled fixture capture/save, navigation, group persistence and a fresh session.
- The offline demo, original DB, credentials and existing servers are preserved. The
  acceptance script refuses existing preparation paths and never overwrites capture files.

## Exact live scope proposed for approval

Scope digest: **`9051c7727c4b0b69b048`**. Host for both requests:
`https://developers.cjdropshipping.com`.

1. At most one `POST /api2.0/v1/authentication/getAccessToken`, JSON containing only the
   existing `apiKey`. Fresh isolated capture process; token acquisition omitted if compatible
   in-process authentication is already available. No token refresh/logout or retry planned.
2. One `GET /api2.0/v1/product/listV2?keyWord=laptop%20stand&page=1&size=10`, authenticated
   using the token. No country, category or price filter. No automatic second page.

Total cap: **two HTTP dispatches, one catalog search, zero retries, 30 seconds**. Auth failure
stops before search. A timeout/uncertain result is durably marked and never resubmitted
automatically. A completed capture is replayed locally, including across process restart.

[CJ product docs](https://developers.cjdropshipping.com/en/api/api2/api/product.html) document
keyword/page/size and the nested catalog response. Product identity, observed USD listing
price and images are retained only where returned; no missing listing URL/variant is invented.
[CJ authentication](https://developers.cjdropshipping.com/en/api/api2/api/auth.html) documents
the token endpoint and API-key body.

[CJ points rules](https://developers.cjdropshipping.com/en/api/api2/standard/points.html),
checked today, list **50 points for listV2** and zero points for unlisted endpoints, including
authentication. Thus the proposed total is **50 quota points** if the search is dispatched.
The documented base is 50,000 points/day; actual account allowance/access is unverified.
There is **no per-call cash fee stated in these docs**. Points are not money; the order-value
conversion is not a points purchase price. No purchase, subscription or billing change is
authorized. We do not claim a measured cash charge of zero or query an account balance.
[CJ frequency limits](https://developers.cjdropshipping.com/en/api/start/limit.html) and
authentication specify one request per second; the existing spacing is retained.

Credential presence only was checked: original checkout `.env` has `CJ_API_KEY`; V5 worktree
`.env` is absent, and the current process has no CJ key. After approval the capture CLI can
read **only CJ_API_KEY into its own process** from the original file. No secret is printed,
copied into the worktree, persisted in evidence or loaded into the preview server.
Token validity and account suspension/quota status remain unknown until the approved call.

## Local completion after the approved capture

Review this page's returned identities/names and explicitly choose three distinct relevant
products. If fewer than three suitable results exist, report the shortfall and stop. Do not
expand the query, page, filters or request scope. Catalog relevance does not prove product
quality, stock or demand.

`finish` saves those exact IDs, repeats the saves to test duplicate prevention, reopens the
repository, saves the three-member group and exports the real catalog observations through
the V4/V5 comparison implementation. Destination SE, quantity 1 and delivery ceiling 14 days
are local investigation assumptions, not observed delivery or Swedish tax advice. No variant,
stock, shipping or demand is fetched. Variant ID stays unknown unless actually observed.
Unadopted costs, profit and demand stay unknown, with an incomplete comparability warning.
Saved baseline heuristic analysis is explicitly not measured demand evidence.

Then open a fresh offline app process against the same dedicated DB on an unused port,
preserving both existing servers. In the browser verify exact saved IDs after restart,
duplicate controls, three-member comparison and the downloaded JSON. Verify actual request
telemetry remains auth≤1/search=1, retries=0; navigation, comparison and export add zero calls.
The preview remains offline throughout, so credentials cannot enable an accidental follow-up.

Prepared commands are in `python -m scripts.v5_live_acceptance --help`. Do **not** run capture
until the user approves the above exact scope. `--approve-scope` records scope; it is not a
replacement for human approval. The exclusive attempt marker also survives interrupted runs.

## Readiness boundary

The reviewed application is appropriate for **single-operator local evaluation** with
explicit research actions and unknown inputs respected. Current-account connectivity and
the new genuine three-candidate flow remain the outstanding acceptance gate. A successful
catalog check will not establish demand, supplier quality, shipping or profitability.
Process-local account cache nonces mean ordinary discovery caches are conservatively not
reused after restart; saved evidence persists, and this acceptance capture has explicit disk
replay. Operator backup/retention discipline is still needed; these are not unattended jobs.

This is **not a hosted private beta**. Authentication, ownership/isolation, provider-funded
quotas, credential policy and production operations remain the separate blockers documented
in [v5-readiness.md](v5-readiness.md). Public launch remains blocked as well. No such hosting
decisions are needed for this bounded local acceptance.
