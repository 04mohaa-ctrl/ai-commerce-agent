# Progress — plan: docs/superpowers/plans/2026-10-06-evidence-research.md

Baseline: feat/evidence-backed-research, clean V1 commit aae060a, tag v1.0.0.
Full original suite: 56 passed. No product functionality changed at baseline.
User supplied explicit implementation brief; proceed incrementally in existing branch.

Docs checked with Context7 and official OpenAI web-search/structured-output guides.
Installed OpenAI 2.54.0 has web_search, URL annotations, include sources and tool cap.
No API key configured at start; asked user to configure .env privately for live acceptance.

Pre-flight: Task 2 consumes Task 1 report/economics/scoring. Task 3 consumes Task 2
repository/provider/service and decorates existing V1 results. Keep research
models independent of Product to avoid schema import cycles. V1 model extensions
use optional/defaulted metadata only.

Task 1: implemented. New tests initially failed (21 absent implementations).
First full run: 75 passed, 2 failed because fixture sources were unused. Fixture
corrected to cite its three publishers; production confidence correctly excluded
unused citations. Economics uses rounded payment fees before net-profit arithmetic.
User configured .env and explicitly authorized live verification without exposing/logging the key.

Task 1: complete — 77 tests passed, including original 56.
Task 2: complete — 18 new tests failed before implementation; afterward full suite: 95 passed.
Additive migration preserves legacy snapshot bytes and uses one transactional migration.
Provider checks actual tool completion/citations and parses qualitative evidence separately.
Task 3: in progress.

Task 3 UI tests: 100 passed. Independent review reproduced citation paragraph
cross-attribution and two retention/fingerprint bugs. Regression tests failed,
then fixes yielded 103 passed. No deferred findings from the reviewer.

Live check: real retrieval reaches classification; classification returns HTTP
429 with a billing/quota indication. No key or raw errors were printed/logged.
Asked user to resolve account/project limit or leave full live verification pending.
Adding persistence of tool-issued citations when the later classification step
fails, without inventing evidence dimensions or high confidence. Two new tests
failed before this addition. Local verification remains underway.

User resolved billing and authorized retry with exact errors if needed, redacting keys.
Real Research product flow then succeeded: initially 8 citations/4 findings.
Inspection exposed parenthesized Markdown citation anchors with inaccurate SDK
offsets; two format regressions failed, then parser matched explicit inline URLs
to tool metadata and preserved only bounded claims. Full suite: 107 passed.
Final live rerun: Pet Hair Remover, 3 citations, 6 accepted findings, insufficient
evidence/low confidence (not an API failure), no observed USD price metadata.
Real UI source links, new-session persistence, demo default and the known
economics example all verified. Physical server restart/browser checks underway.
Added a failing timestamp regression: effective V2 analysis must use the research
timestamp while the original V1 snapshot stays untouched; fixed by display composition.

Final full suite: 108 passed; original 56 test files unchanged. Lint, formatting,
compileall and whitespace checks passed. Actual server was stopped/restarted;
browser Sources showed 3 clickable links and Economics showed the persisted
known example (25 gross / 15.80 net / 39.50% net margin / 23.80 break-even CPA).
A separate keyless process started with 12 demo products and safe research fallback.
No secrets printed/logged/committed. Current live result is valid insufficient
evidence with low confidence; it is not an API failure. Source summaries and
their numbers are explicitly unverified AI JUDGEMENT. No deferred review findings.
All V2 implementation and acceptance work complete; final docs and preview delivered locally.

Research UX follow-up: exact names route to the shared research action; unmatched
names offer an explicit one-click custom candidate, and category/tag queries keep
candidate listings. Custom prices/costs are unknown nullable JSON values; no SQL
migration or duplicated provider. Added nine entry/unknown-value/filter tests.
Full suite: 117 passed. Focused independent review found no material issues.
Browser verified Electric heated lunch box creation and automatic Research tab
focus with Demo Mode intact; existing saved products/citations/economics preserved.
