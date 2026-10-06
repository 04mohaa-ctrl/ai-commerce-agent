# V2 verification — 2026-10-06

**Research entry UX follow-up:** the current full suite passes **117 tests**.
Specific names now select/create a candidate and reuse the existing web-research
action; categories continue listing candidates. See
[the UX verification addendum](verification-research-entry.md). The 108-test
record below describes the original V2 implementation before this follow-up.

## Result

V2 extends the existing V1 architecture on feat/evidence-backed-research.
The v1.0.0 checkpoint remains aae060af00d6fa3f6e7efd8c5baa28e32395ad1d.
The original 56 tests are unchanged. All **108 tests passed** in the final full
suite (11.63 seconds), including 52 new V2 checks. Ruff lint, formatting,
compileall and Git whitespace checks passed.

## Added and extended files

Added:

- src/research/models.py — sources, findings, qualitative dimensions, reports and attempts.
- src/research/research_service.py — explicit research, cache and safe demo/failure handling.
- src/research/scoring.py — deterministic confidence, net-margin scoring and display composition.
- src/research/providers/base.py — provider protocol and product fingerprints.
- src/research/providers/web_research.py — Responses web search, citation parsing and extraction.
- src/research/providers/prices.py — bounded retail JSON-LD price observation.
- src/services/economics.py — validated inputs and deterministic decimal unit economics.
- src/ui/research_details.py — Research, Sources and Economics views.
- tests/test_economics.py, test_evidence_scoring.py, test_web_research.py,
  test_research_database.py, test_research_app.py and shared test fixtures.
- docs/v2-research.md and V2 design/plan/progress/verification documents.

Extended:

- src/database/database.py — additive transactional version-2 migration and upserts.
- src/schemas/product.py — backward-compatible optional score metadata.
- src/config.py and .env.example — separate OPENAI_RESEARCH_MODEL setting.
- src/ui/products.py, dashboard.py, research.py and settings.py — V2 composition/navigation.
- requirements.txt — declare directly used httpx; it was already installed and locked.
- README.md — V2 usage and compatibility guidance.

## Data source and live example

Provider: OpenAI Responses API **web_search**, using **gpt-4.1-mini**, followed
by Pydantic Structured Outputs for qualitative classification. Context7 and
official documentation were checked before coding. Citation URLs/titles come
from actual tool annotations, not classifier-generated references. Observed
prices require independently read matching USD retail Product/Offer JSON-LD.

Researched **Pet Hair Remover** through the actual Research product UI action
using the locally configured key. The final run retained **3 source links and
6 accepted source-linked findings**. Classification and UI processing completed
successfully; the research outcome was **Insufficient evidence / low confidence**.
It found product/marketing statements but insufficient competition/trend support.
No matching USD listing metadata was observed, so observed_price_range remains
unavailable. The app did not manufacture missing market evidence or prices.

Actual cited URLs in the final report:

- https://www.pawvortex.com/products/chomchom-roller-pet-hair-remover
- https://myfurfriend-store.myshopify.com/products/furfriend-reusable-pet-hair-remover-roller
- https://furquo.myshopify.com/products/furquo-reusable-pet-hair-roller

These are seller/product pages, not independent proof of demand, sales or growth.
Their summaries, including any reported numbers, remain explicitly labeled
AI JUDGEMENT / unverified search-report context. Citation provenance and access
dates are observed; this does not certify the publisher's claims.

An initial classification request encountered HTTP 429 with a billing/quota
indication. The user configured API billing; subsequent real UI requests and
classification succeeded. The API key and raw credential-bearing errors were
never printed, logged or committed. Only credential-safe diagnostic metadata
was inspected, and the helper was prepared to redact exact errors if needed.

## Persistence, restart and economics

Verified the following after the real request:

- Source links render inline and in Sources, with UTC access dates.
- A fresh app session reads the stored research, citations and financial inputs.
- Stopped the actual Streamlit server, started a new process and opened Saved Products.
- The browser Sources panel still contained **3 clickable source links**.
- Browser Economics retained USD40 selling price, USD10 cost, USD5 shipping,
  3% payment fee and USD8 estimated ads.
- Browser outputs matched the independently hand-checked example:
  gross profit **USD25**, gross margin **62.50%**, fees **USD1.20**,
  net profit **USD15.80**, net margin **39.50%**, break-even CPA **USD23.80**.
- Original V1 saved-product data remained readable; the existing shortlist entry was preserved.
- Default Demo Mode remained enabled in a new session while stored web evidence stayed viewable.
- A separate process overriding OPENAI_API_KEY to empty (without changing local .env)
  started with 12 demo products and used the safe Research product demo fallback.

The app remains running locally at http://127.0.0.1:8501. Its server has the
network access needed for explicit web-research actions, and is bound only to
the local computer. API calls require disabling Demo Mode in Settings.

The real report and financial example remain in the local Git-ignored database.
Credential-free verification JSON/screenshots and a consistent pre-verification
SQLite backup are in Git-ignored artifacts/. .env remains ignored and unchanged.

## Review and regression checks

An independent read-only reviewer reproduced three material edge cases:
paragraph-wide cross-attribution of citations, loss of partial evidence on demo
refresh, and stale fingerprints preventing new partial reports from persisting.
Each was reproduced with failing regression tests and fixed.

Live verification additionally exposed parenthesized Markdown citation links
and inaccurate annotation offsets. Two failing real-format fixtures were added;
the parser now matches explicit inline URLs against tool-issued metadata and
bounds context to the supporting claim. It does not borrow unrelated paragraph
text. Extra tests cover preserving real citations if classification later fails,
and using the actual research timestamp without mutating a V1 saved snapshot.

No unresolved review findings remain. Local unit/integration/UI tests use fake
transports and temporary databases; regular pytest runs make no paid API calls.

## Known limitations and next step

General web search is a source-discovery and synthesis tool, not independent
verification of market statistics. Web evidence confidence is capped at medium;
the real example appropriately stayed low. Publication dates, publisher ownership,
page-level truth and semantic entailment are not independently audited.

Price observations have bounded allowlisted coverage and heuristic product-name
matching. Blocked pages, variants, unavailable JSON-LD and non-USD prices yield
no observed range. Financial assumptions remain estimates and exclude tax,
returns, fixed transaction fees and fixed overhead. Research is sequential and
the database keeps a latest snapshot/attempt rather than full historical versions.

Recommended next step: dated independent demand/trend data and page-level
verification, followed by a structured retail-price provider and landed-cost/
returns estimates. Commerce automation remains outside this version.
