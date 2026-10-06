# V2 Evidence-backed Research Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans task by task.

**Goal:** Extend V1 with source-linked research and deterministic net economics.
**Architecture:** Compose new research providers/reports with existing Product,
ResearchResult and SQLite repository; keep V1 source and analyst interfaces.
**Tech Stack:** Installed OpenAI 2.54 Responses API, Pydantic, sqlite3, Streamlit,
httpx, pytest; stdlib JSON-LD metadata parser, no fragile selectors.
**Spec:** ../specs/2026-10-06-evidence-research-design.md

## Global Constraints

- Preserve all existing 56 tests and the v1.0.0 checkpoint.
- Only environment/.env credentials; no secret output or source-control secrets.
- No model-generated final score, confidence or verified market numbers.
- Sources must derive from actual tool citations, with claim-to-source mapping.
- Unknown financial assumptions are None, not silently zero.
- Migrate additively; keep previous evidence if an external refresh fails.

## Review Focus

- Fabricated links/excerpts and incompatible currencies cannot become evidence.
- Repeated source URLs, tracking parameters and repeated refreshes cannot duplicate records.
- Missing key, refusals, timeouts and malformed output must render safe states.
- Historical V1 snapshots and stale/changed-product research remain distinguishable.
- Net economics with unknown/negative profit must not imply profitable acquisition.

### Task 1: Validated contracts, economics and evidence scoring

Files: src/research/models.py, src/services/economics.py,
src/research/scoring.py, tests/test_economics.py, tests/test_evidence_scoring.py.
Produces EconomicsInputs/EconomicsResult/calculate_economics, Source,
EvidenceFinding/WebResearchExtraction/ResearchReport, calculate_evidence_score.

- [x] Write tests for known arithmetic, unknown costs, invalid values, citation
  identity/validation and deterministic confidence/score handling.
- [x] Run tests RED; implement schemas, decimal calculations and confidence rules.
- [x] Run the complete suite GREEN.

### Task 2: Web provider and research persistence

Files: src/research/providers/{base,web_research,prices}.py,
src/research/research_service.py, src/database/database.py, src/config.py,
tests/test_web_research.py, tests/test_research_database.py.
Consumes Task 1 types/scoring and existing Product/Repository/Settings.
Produces WebResearchProvider.research(product, progress),
EvidenceResearchService.research_product(product, force), repository research/
attempt/economics accessors, settings.research_model.

- [x] Write failing transport tests for real SDK web search + structured parse,
  citation validation, missing evidence, failures, duplicate URLs, price metadata.
- [x] Write failing migration/source/research/economics persistence tests against
  exact legacy schema/JSON and a fresh repository.
- [x] Implement provider interface, citation parsing and bounded metadata reads.
- [x] Implement transactional additive migration and per-product upserts.
- [x] Implement offline fallback, explicit cache/refresh and failed-attempt retention.
- [x] Run all tests GREEN; inspect dependency interfaces for compatibility.

### Task 3: Compose UI and verify delivery

Files: src/ui/research_details.py, src/ui/products.py, src/ui/dashboard.py,
src/ui/settings.py, src/schemas/product.py, .env.example, README.md,
tests/test_research_app.py, docs/verification-v2.md.
Produces Research/Economics/Sources views and effective evidence scores in V1 table.

- [x] Write failing AppTest flows for no research, demo fallback, success fixture
  citations, failure retention, manual economic edits and fresh-session persistence.
- [x] Add durable settings and UI controls, show missing-data/uncertainty states.
- [x] Integrate evidence-based scores without breaking old analysis/save interfaces.
- [x] Run full suite, lint, formatting and compilation; fix actual failures.
- [x] Perform independent read-only review and regression-test material findings.
- [x] Launch actual Streamlit and verify research, source links, economics and restart.
- [x] Perform one real provider research if a key is locally configured; otherwise
  explicitly leave this acceptance check pending rather than claiming completion.
- [x] Update README and verification report with exact checks/limitations.
