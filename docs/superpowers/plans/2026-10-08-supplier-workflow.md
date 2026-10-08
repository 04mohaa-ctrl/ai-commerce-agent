# Supplier workflow completion

> Use superpowers:executing-plans inline. User authorizes implementation and prohibits commits.

Goal: complete explicit requirements → selection → freight → separate adoption without provider calls during diagnosis.
Architecture: supplier requirements use a namespaced record in existing V4 settings; product description and demand identity remain independent. Matching retains conservative missing-attribute gates. Quotes are chosen explicitly for the selected immutable variant/stock cohort. Diagnostics store only allowlisted failure classifications/status numbers.
Tech: Python, SQLite, Pydantic, Streamlit, pytest/httpx replay.
Spec: user request and docs/v4-real-demand-supplier.md matching/lifecycle contract.

Constraints: preserve existing uncommitted work, user DB/.env/servers, variant/warehouse/freshness/scoring guards. No external requests, payment, commits or deployment.

- [x] Requirements: failing UI regression for visible required-color input and missing-target/supplier distinction; implement SupplierRequirements, namespaced persistence, matching integration and synchronized product-specific forms. Test restart, conflicts and accessory rejection.
- [x] Freight: failing UI regression for post-refresh quote choice and adopted-cost preservation; implement pure dispatch gate, actionable request states and explicit cohort-bound quote selection. Replay repository freight contract response; no captured live Swedish quote exists.
- [x] Demand/config: failing diagnostic classification tests for timeout/HTTP/provider/invalid/empty and safe launch precedence; retain old UNKNOWN failure honestly, propagate safe notices, surface 3/52 sparse historical evidence, configure missing process provider keys at app startup.
- [x] Verification: full suite/lint/format/whitespace, fresh browser instance with isolated copied saved data, save/recheck/select/replayed freight/adopt/restart. Diagnose stale imports on original 8502 and verify fresh fixed process on 8503 without writes, preserve original DB/env hashes and process IDs.

Review focus: stale cross-tab widgets; changed requirements with historical selections; refreshed quotes invalidating an already-adopted supplier cost; failed response reason lost between adapters; absent/empty environment values versus dotenv secrets.
