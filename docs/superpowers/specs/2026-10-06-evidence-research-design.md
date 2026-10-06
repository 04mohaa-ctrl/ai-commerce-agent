# V2 evidence-backed research design

## Intent and boundaries

Extend the verified V1 on feat/evidence-backed-research without replacing its
source/agent/service architecture or changing the v1.0.0 checkpoint. Existing
56 tests and keyless demo/manual/saved flows remain supported. V2 adds product
research with citations, explicit confidence, deterministic economics and
backward-compatible persistence. No commerce automation or agent orchestration.

## Research layer

src/research/models.py defines Source, EvidenceFinding, ResearchReport and
qualitative extraction schemas. Providers implement ResearchProvider.research
for one Product. WebResearchProvider uses the installed OpenAI Responses SDK:
first responses.create with web_search, tool_choice=required and the full source
list included; then responses.parse classifies the retrieved material. Only
URLs in actual URL-citation annotations may support evidence. Invented links,
unsupported claims and missing citation records are rejected. Normalized URLs
deduplicate sources; every finding contains source IDs and an exact supporting
excerpt from the cited retrieval context. Retrieval text is an AI summary of
cited pages, not an independently verified page quotation.

The report includes product_name, research_summary, observed_price_range,
demand_evidence, competition_evidence, trend_evidence, marketing_angles,
common_customer_complaints, risks, sources, confidence_level and researched_at.
Qualitative dimensions use weak/moderate/strong/unknown, never a final LLM score.
Provider output contains no LLM-set confidence or total score.

Displayed observations are explicitly source-linked reports; interpretations
are AI JUDGEMENT and manual financial inputs are ESTIMATED. Exact market counts
and growth percentages are not accepted as verified quantitative data. Observed
USD prices are populated only by deterministic extraction of Product/Offer
JSON-LD from cited, allowlisted retail pages, with comparable product-name
matching. No selector scraping or invented price ranges; absent usable metadata
means no observed range. Numeric claims in qualitative AI summaries remain
unverified and are never labeled verified statistics.

The web provider defaults to gpt-4.1-mini (documented Responses web-search
support), configurable through OPENAI_RESEARCH_MODEL. The existing V1 model
setting remains intact. Two bounded SDK calls, no retries, and optional retail
metadata lookups run only on explicit Research product submissions. No key or
explicit demo mode returns Insufficient evidence with empty sources and a
visible demo notice. Failures expose sanitized messages, never raw SDK errors.

## Economics and scores

Inputs: product_cost, selling_price, optional shipping_cost,
payment_fee_percent and estimated_ad_cost_per_order. Currency is USD, matching
V1. Values must be finite/nonnegative, fee percent <=100, selling price >0.

- gross_profit = selling_price - product_cost - shipping_cost
- gross_margin_percent = gross_profit / selling_price * 100
- payment_fee = selling_price * payment_fee_percent / 100
- estimated_net_profit = gross_profit - payment_fee - estimated_ad_cost_per_order
- estimated_net_margin_percent = estimated_net_profit / selling_price * 100
- break_even_ad_cost = gross_profit - payment_fee

Unknown inputs produce unavailable dependent outputs, not guessed zero costs.
Negative break-even CPA means there is no profitable nonnegative acquisition
cost. Money uses decimal arithmetic and two-decimal display; score computation
uses the deterministic calculated net margin. Taxes, returns and fixed overhead
are excluded and disclosed.

Original estimate scoring remains until product research is performed.
Research scoring maps weak/moderate/strong to 3/6/9, unknown demand/trend/
marketing to 0 and unknown competition to 10 (no benefit from missing evidence).
Weights remain 25/25/20/15/15, but V2 uses estimated NET margin for the 25% profit
factor. Missing net economics gives no profit points. Source-linked dimensions
with no accepted findings become unknown. Confidence is low with fewer than
three independent publisher domains or missing demand/competition/trend; else
medium. Automated web summaries never qualify as high-confidence verification.
Apply low=0.5, medium=0.85, high=1.0 to the weighted total, visibly showing the
raw score and adjustment. These are prioritization rules, not calibrated
probabilities. Evidence older than seven days is conservatively low confidence.

## Persistence and UI

Additive SQLite migration in one transaction, version 2, creates independent
research_records, research_sources, research_attempts and economics tables.
V1 saved_products/candidates JSON and tables remain untouched. Keep one latest
research snapshot and one latest attempt per canonical product, plus unique
sources per product; explicit refresh replaces the snapshot. A failed attempt
must preserve the previous usable report. Persist product fingerprint to avoid
using research for a changed product description/category. Economics are
independent of source facts. Research and economics persist even before Save
product. Saved snapshots retain V1 compatibility; effective displayed scores
include current research and economic inputs without rewriting stored V1 data.

Product Details adds Research, Sources and Economics views and Research product.
Show No research performed, Researching, Research completed, Research failed,
Insufficient evidence. Inline finding citations and source lists are clickable
with UTC access timestamps; raw AI retrieval report is not a verified-data panel.
Saved reports remain viewable in keyless mode. The new research button respects
the durable demo setting; navigation never triggers external calls. Editing
economic assumptions recomputes scores without any model request.

## Acceptance

Preserve original tests; add parsing/citations, missing evidence/key, failures,
source deduplication, finance arithmetic/unknown costs, confidence, safe additive
migration and AppTest research/economics/restart tests. Run all tests, lint and
compile checks, launch Streamlit, verify offline flow, citations with a real SDK
transport fixture, persistence after restart, and manually check USD40 price,
USD10 cost, USD5 shipping, 3% fees, USD8 ads => USD25 gross profit, 62.5% gross
margin, USD15.80 net profit, 39.5% net margin, USD23.80 break-even CPA.
The required real OpenAI web research check needs a locally configured key;
request its configuration early and report that check as pending if absent.
