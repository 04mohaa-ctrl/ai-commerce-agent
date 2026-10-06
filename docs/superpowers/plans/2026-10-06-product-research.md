# Product Research V1 Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans task by task.

**Goal:** Implement the user's complete local Product Research V1.
**Architecture:** Pydantic domain objects, deterministic scoring, one analyst,
pluggable sources, SQLite repositories and Streamlit views.
**Tech Stack:** Python 3.12+, Streamlit, sqlite3, OpenAI SDK, dotenv, pytest.
**Spec:** ../specs/2026-10-06-product-research-design.md

## Global Constraints

- Offline demo works without OPENAI_API_KEY. Never expose a key or raw SDK errors.
- Explicitly separate verified evidence, estimated inputs and analyst judgements.
- Weights: demand 25%, margin 25%, trend 20%, inverted competition 15%, marketing 15%.
- Keep one agent; no scraping, browser workflows or multi-agent orchestration.
- All durable local state is in SQLite; canonical identity prevents duplicates.

## Review Focus

- Zero/negative/non-finite prices and out-of-range score inputs must be rejected.
- Live refusal, invalid schema, timeout and credential errors must preserve demo usability.
- Equivalent names with case/Unicode/whitespace differences must not duplicate saved rows.
- Reruns/navigation must not trigger live API requests or silently replace saved snapshots.
- No search matches or filters excluding all products must render useful empty states.

### Task 1: Domain and scoring

Files: src/schemas/product.py, src/services/scoring.py, tests/test_scoring.py.
Produces: Product, Assessment, ResearchResult; gross_margin(cost, price),
score_breakdown(assessment, margin), recommendation(score), build_result(...).

- [x] Write arithmetic, inversion, thresholds and invalid-input tests first.
- [x] Run tests; expect missing implementation failures.
- [x] Implement typed domain and deterministic calculations.
- [x] Run pytest tests/test_scoring.py; expect all passing.

### Task 2: Sources, agent and persistence

Files: src/config.py, src/sources/local.py, src/agents/product_research_agent.py,
src/database/database.py, src/services/product_service.py, data/demo_products.json,
tests/test_agent.py, tests/test_database.py, tests/test_products.py.
Consumes Task 1 models/calculations. Produces ProductResearchAgent.analyze(product),
ProductRepository.save/list_saved/remove_saved/add_candidate/list_candidates,
LocalProductSource.search(query), filter_results(results, ...), research(query).

- [x] Write source, agent, missing-key, SDK-boundary, persistence and filter tests.
- [x] Run new tests; expect failures from absent behavior.
- [x] Implement JSON seed, source protocol, deterministic analyst and optional SDK adapter.
- [x] Implement SQLite snapshot upsert and durable manual candidates.
- [x] Run full pytest suite; expect all passing.

### Task 3: Application and delivery

Files: app.py, src/ui/dashboard.py, src/ui/products.py, src/ui/research.py,
src/ui/settings.py, tests/test_app.py, README.md, scripts/start.ps1.
Consumes Task 2 services and repository; produces a complete local Streamlit app.

- [x] Write AppTest flows for research/details/save/restart/remove/manual entry.
- [x] Run new tests; expect the app to be absent.
- [x] Implement clean UI, metrics, sort/filter controls and evidence/scoring details.
- [x] Document install, venv, env, launch, tests, architecture and extension points.
- [x] Run all pytest tests and lint/compile checks; inspect all failures.
- [x] Start real Streamlit server, check health and open local preview.
- [x] Review complete implementation against the spec; fix material findings with regression tests.
- [x] Record exact verification and limitations in docs/verification.md.
