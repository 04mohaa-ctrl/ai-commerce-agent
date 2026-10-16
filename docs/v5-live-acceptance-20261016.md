# V5 bounded live acceptance — completed 16 October 2026

**Passed for the approved single-operator discovery/save/compare/export scope.**
No hosted private beta or public launch readiness is implied. Application code is unchanged
from the preceding 770-test validation; this run added genuine local evidence and this report.

## Actual provider requests

User approval: `9051c7727c4b0b69b048`. Only the isolated
`data/v5-live-acceptance-20261016.db` was used. Capture ran once in a fresh process with the
existing original-checkout CJ key read privately into that process; no credential file changed.

- One `POST https://developers.cjdropshipping.com/api2.0/v1/authentication/getAccessToken`.
- One `GET https://developers.cjdropshipping.com/api2.0/v1/product/listV2`, parameters exactly
  `keyWord=laptop stand`, `page=1`, `size=10`; no other filters.
- **Two HTTP dispatches total, zero retries, zero cache hits; 3.485 seconds** against a
  30-second absolute deadline. Search completed at **2026-10-16 08:09:41.451700 UTC**.
- Adapter status **SUCCESS**, ten parsed catalog records, `partial=false`.
- No detail, variant, stock, freight, demand, OpenAI, account-balance or next-page request.
  No ordering, credit purchase or billing change. No requests after capture.

[CJ's documented quota schedule](https://developers.cjdropshipping.com/en/api/api2/standard/points.html)
assigns 50 points to this catalog search and zero to unlisted authentication: **50 documented
quota points for the dispatched scope**. The adapter does not retain `pointsInfo`, so an actual
account-balance deduction was not independently measured. No per-call cash fee is stated in
that schedule; no measured cash charge is asserted and points are not converted to dollars.

## Genuine candidates saved

Selected three distinct laptop-stand titles from this one response for further investigation:

- **Foldable laptop stand** — CJ `4C56FFFA-399B-4E05-98C6-092BB3A724A9`;
  observed catalog price **USD 3.10**.
- **New Laptop Stand Multifunctional Folding Lift Portable Laptop Stand Monitor Increase
  Rack Aluminum Alloy Base** — CJ `DCB495CC-80F8-4ED9-B5BD-26E39B751776`;
  observed catalog price **USD 11.82**.
- **Laptop Stand Desktop Aluminum Alloy Heat Dissipation** — CJ `2508270727211626000`;
  observed catalog price **USD 11.61**.

These are catalog observations, not selected variant costs, landed costs or adopted financial
inputs. Image URLs were returned and retained as evidence; no image download was needed.
Listing URLs, brand and category were absent and remain absent. Variant IDs are unknown.
Title relevance is sufficient for a research shortlist, not proof of quality or exact fit.

Other returned records included phone mounts, desk converters, a car table and a plant stand;
none was saved. No query expansion or extra page was required.

## Local acceptance checks

The existing production save/comparison code was used, with no injected provider response:

1. Saved all three exact CJ product identities and original catalog observation timestamps.
   Repeated every save twice more: **six repeat saves, still exactly three candidates and
   three saved products**. The initial finish operation also checked duplicate identity.
2. Reopened the database in a separate Python process and verified all three identities,
   origins, settings and one saved comparison group. No synthetic candidates were inserted.
3. Started a **new offline app process at http://127.0.0.1:8512**, reading the same isolated
   DB. This verifies persistence independent of the capture process and previous server's
   memory. Existing servers 8510 and 8511 were left running.
4. In the actual browser, Dashboard showed three saved products. Candidates showed the
   exact saved CJ identity, `provider_observation` provenance, disabled supplier/shipping/
   demand actions, unavailable measured demand, blank financial inputs and unknown profit.
5. Compare reopened **V5 catalog acceptance** with the three correct names/members and
   notes. It showed incomplete scenarios, no direct comparability, 0% opportunity evidence
   coverage and no winner. SE/quantity 1/USD are shared local assumptions; VAT is UNKNOWN.
6. Downloaded **Export V5 comparison and evidence (JSON)** from the browser. Parsed the
   actual downloaded file and matched its three IDs, group members and complete catalog
   origins against the CLI export. Both preserve null demand/selection/profit/financial inputs
   and `directly_comparable=false`. Separate export times are retained honestly.
7. Repeated actual app navigation Candidates → Compare → Dashboard → Compare under HTTPX
   and HTTPcore socket guards using the saved genuine DB, without fixture responses.
   **Zero attempted provider requests**, no UI exceptions, correct saved membership.
   The app process remained in `COMMERCE_OFFLINE=1` throughout browser checks.

The default saved V4 deterministic/demo baseline analysis is explicitly heuristic, not new
measured market evidence. Its existence does not populate the measured-demand snapshots or
economic inputs; those remain unknown. No financial cost was automatically adopted.

## Evidence and preservation

Ignored local artifacts under `artifacts/v5-live-acceptance-20261016/`:

- `scope.json`, `attempt-started.json`: approved scope and consumed request guard.
- `capture.json`, `capture-provenance.json`: sanitized **NEW_V5_LIVE** catalog/telemetry.
- `comparison.json`: local completion export with explicit acceptance provenance.
- `browser-comparison.json`: actual browser download, copied without altering the download.
- `local-verification.json`, `browser-verification.json`: identity, duplicate, unknown-field
  and guarded-navigation checks. Capture SHA-256:
  `3122409f386c25a551a93787dfb9c4c697d6efb30a399a5d2e8c955626aac42f`.

The successful capture is now consumed and replayable from disk; do not repeat live capture.
The original DB and credential files were not written, and the synthetic demo DB was not
used for this flow. At completion, application changes remained uncommitted on
`codex/v5-discovery-comparison`; the user subsequently authorized a commit/push of that feature
branch. Raw captures, databases, exports, logs, backups and review patches remain ignored local
artifacts and are excluded from publication. No merge, tag or deployment is authorized.

## Evidence boundaries and remaining blockers

- **Offline/synthetic:** preceding full suite **770 passed**, lint/format/compile/diff checks;
  fixture behavior does not become live evidence. The labeled demo remains at port 8510.
- **Historical V4 live:** unchanged genuine variant/stock/freight and sparse demand captures
  described in [verification-v4.md](verification-v4.md); not refreshed or imported here.
- **New V5 live:** this catalog response plus local persistence/comparison/export acceptance.
  Only current CJ authentication and this exact page/query are live verified.

There is **no remaining blocker in the approved bounded acceptance flow**. Single-operator
local investigation can proceed with explicit requests. Product fit/variant choice, stock,
freight, delivery, measured demand, tax/FX and complete economics still need evidence or user
inputs before a commercial decision. Catalog presence and price do not establish a winner.
Ordinary catalog caches remain conservatively process-scoped; saved records/evidence persist.

Hosted private beta and public launch remain blocked by the ownership/authentication,
credential funding, per-user spending controls, operations and provider-permission work in
[v5-readiness.md](v5-readiness.md). This local acceptance did not implement or authorize hosting.
