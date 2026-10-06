# Product-or-category Research UX verification — 2026-10-06

The entry point now accepts a specific product name or a broad category.
Exact canonical names reuse existing candidates and run the same shared
run_product_research action as Product Details. Unmatched names offer an
explicit Research this product action, with no mandatory manual-entry form.
Known categories/tags continue returning relevant candidates. Blank queries
continue listing candidates and do not offer an empty custom product.

Custom candidates are stored only after the explicit action, with category
Other and unknown product cost/selling price. Canonical name matching prevents
duplicate custom entries and does not overwrite existing candidate prices,
research or economics. Unknown prices are represented as nullable JSON values;
the existing SQLite tables and migration version are unchanged. Old records
with known prices continue validating and calculating identically.

The same V2 research service/provider handles both buttons. Candidate setup
is offline, so a specific-product action does not also spend an estimate-only
model request. Direct entry focuses the Research tab and clears old filters
which could hide the selected product. Known/unknown economics and margins
render safely; unknown margins sort last and cannot pass a minimum-margin filter.

Added tests in tests/test_research_entry.py cover:

- Exact existing product and canonical name normalization.
- New arbitrary product, one-click research and source/saved-product integration.
- Broad category and related local candidates.
- No results, explicit custom action, and blank-search recovery.
- Duplicate custom product retaining economics and Demo Mode.
- Unknown prices/profits, numeric sorting/filtering and excluding-filter recovery.

All **117 tests passed** in the full suite (15.20 seconds), preserving the
previous 108 tests. Ruff lint/format checks and compilation passed. The focused
independent read-only review found no material issues and independently passed
all nine new entry tests. No real API requests were needed for these regression
tests; live routing uses the already verified V2 research implementation.

Browser verification used Electric heated lunch box in the main input: unmatched
search offered Research this product; clicking it created one custom candidate
and opened Product Details with Research selected. Demo Mode was preserved,
and the card showed Unknown for cost, selling price and margin. Existing saved
products were left intact. Screenshot: artifacts/research-entry-ux.png.

Functional changes: src/ui/research.py, shared UI action in
src/ui/research_details.py, resolver methods in src/services/product_service.py,
nullable-price handling in schemas/product.py, services/economics.py,
services/scoring.py, agents/product_research_agent.py, research/scoring.py and
the existing product UI. V1/V2 data, citations, saved products and economics
remain compatible. No new scraper, research provider or duplicate pipeline was added.
