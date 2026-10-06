import sqlite3

from tests.research_fixtures import report_fixture


def test_additive_migration_keeps_v1_snapshot_bytes_and_models(tmp_path, result):
    from src.database.database import ProductRepository

    path = tmp_path / "legacy.db"
    payload = result.model_dump_json()
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE saved_products (product_id TEXT PRIMARY KEY,payload TEXT NOT NULL,"
            "schema_version INTEGER NOT NULL DEFAULT 1,"
            "saved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.execute(
            "CREATE TABLE candidates (product_id TEXT PRIMARY KEY,payload TEXT NOT NULL,"
            "schema_version INTEGER NOT NULL DEFAULT 1)"
        )
        conn.execute(
            "INSERT INTO saved_products(product_id,payload) VALUES(?,?)",
            (result.product.id, payload),
        )
    repo = ProductRepository(path)
    assert repo.list_saved() == [result]
    assert repo.get_research(result.product.id) is None
    assert repo.get_economics(result.product.id) is None
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT payload FROM saved_products").fetchone()[0] == payload
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2


def test_report_sources_timestamp_and_confidence_survive_reopen_without_duplicates(
    tmp_path, product
):
    from src.database.database import ProductRepository

    path = tmp_path / "research.db"
    repo = ProductRepository(path)
    report = report_fixture()
    report.sources.append(report.sources[0])
    repo.save_research(product.id, report)
    repo.save_research(product.id, report)
    reopened = ProductRepository(path)
    saved = reopened.get_research(product.id)
    assert len(saved.sources) == 3
    assert saved.researched_at == report.researched_at
    assert saved.confidence_level == "medium"
    assert saved.demand_evidence[0].source_ids == [saved.sources[0].id]
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM research_records").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM research_sources").fetchone()[0] == 3


def test_economic_inputs_persist_without_rewriting_original_snapshot(tmp_path, result):
    from src.database.database import ProductRepository
    from src.services.economics import EconomicsInputs

    path = tmp_path / "research.db"
    repo = ProductRepository(path)
    repo.save(result)
    inputs = EconomicsInputs(
        product_cost=10,
        selling_price=40,
        shipping_cost=5,
        payment_fee_percent=3,
        estimated_ad_cost_per_order=8,
    )
    repo.save_economics(result.product.id, inputs)
    assert ProductRepository(path).get_economics(result.product.id) == inputs
    assert repo.list_saved() == [result]


def test_failed_refresh_keeps_previous_sources_and_persists_failure(tmp_path, product):
    from src.database.database import ProductRepository
    from src.research.providers.base import ResearchProviderError
    from src.research.research_service import EvidenceResearchService

    class Provider:
        def research(self, product, progress=None):
            raise ResearchProviderError("External research unavailable.")

    repo = ProductRepository(tmp_path / "research.db")
    repo.save_research(product.id, report_fixture())
    service = EvidenceResearchService(repo, api_key="test-secret", provider=Provider())
    result = service.research_product(product, force=True)
    assert result.status == "failed"
    assert repo.get_research(product.id).sources
    assert repo.get_research_attempt(product.id).status == "failed"


def test_missing_key_returns_persisted_demo_without_fabricated_evidence(tmp_path, product):
    from src.database.database import ProductRepository
    from src.research.research_service import EvidenceResearchService

    class NeverProvider:
        def research(self, *args, **kwargs):
            raise AssertionError("Missing key must not call provider")

    path = tmp_path / "research.db"
    service = EvidenceResearchService(ProductRepository(path), api_key="", provider=NeverProvider())
    result = service.research_product(product)
    assert result.status == "insufficient"
    assert result.mode == "demo" and result.sources == []
    assert result.research_summary == "Insufficient evidence"
    assert "Demo Mode" in result.notice
    assert ProductRepository(path).get_research(product.id).mode == "demo"


def test_cached_completed_report_avoids_external_call_and_changed_description_invalidates(
    tmp_path, product
):
    from src.database.database import ProductRepository
    from src.research.research_service import EvidenceResearchService

    class Provider:
        calls = 0

        def research(self, product, progress=None):
            self.calls += 1
            return report_fixture()

    provider = Provider()
    service = EvidenceResearchService(
        ProductRepository(tmp_path / "research.db"), api_key="test-secret", provider=provider
    )
    service.research_product(product)
    service.research_product(product)
    assert provider.calls == 1
    service.research_product(
        product.model_copy(update={"description": "A materially different product"})
    )
    assert provider.calls == 2


def test_demo_request_does_not_erase_previous_completed_web_evidence(tmp_path, product):
    from src.database.database import ProductRepository
    from src.research.research_service import EvidenceResearchService

    repo = ProductRepository(tmp_path / "research.db")
    from src.research.providers.base import product_fingerprint

    existing = report_fixture()
    existing.input_fingerprint = product_fingerprint(product)
    repo.save_research(product.id, existing)
    report = EvidenceResearchService(repo, api_key="").research_product(product, force=True)
    assert report.mode == "demo" and report.sources == []
    assert repo.get_research(product.id).status == "completed"
    assert len(repo.get_research(product.id).sources) == 3
    assert repo.get_research_attempt(product.id).status == "insufficient"


def test_demo_preserves_partial_citations_and_changed_input_accepts_fresh_partial_report(
    tmp_path, product
):
    from src.database.database import ProductRepository
    from src.research.providers.base import product_fingerprint
    from src.research.research_service import EvidenceResearchService

    repo = ProductRepository(tmp_path / "research.db")
    partial = report_fixture()
    partial.status = "insufficient"
    partial.input_fingerprint = product_fingerprint(product)
    repo.save_research(product.id, partial)
    EvidenceResearchService(repo, api_key="").research_product(product, force=True)
    assert len(repo.get_research(product.id).sources) == 3

    completed = partial.model_copy(update={"status": "completed"})
    repo.save_research(product.id, completed)
    changed = product.model_copy(update={"description": "A revised fabric-specific roller"})

    class Provider:
        def research(self, product, progress=None):
            return partial.model_copy(deep=True)

    fresh = EvidenceResearchService(
        repo, api_key="test-secret", provider=Provider()
    ).research_product(changed, force=True)
    stored = repo.get_research(product.id)
    assert stored.input_fingerprint == product_fingerprint(changed)
    assert stored.researched_at == fresh.researched_at
    assert stored.status == "insufficient" and len(stored.sources) == 3


def test_midflow_failure_persists_new_citations_when_prior_attempt_had_none(tmp_path, product):
    from src.database.database import ProductRepository
    from src.research.models import ResearchReport
    from src.research.providers.base import ResearchProviderError, product_fingerprint
    from src.research.research_service import EvidenceResearchService

    repo = ProductRepository(tmp_path / "research.db")
    fingerprint = product_fingerprint(product)
    repo.save_research(
        product.id,
        ResearchReport(product_name=product.name, status="failed", input_fingerprint=fingerprint),
    )
    partial = report_fixture()
    partial.status = "failed"
    partial.input_fingerprint = fingerprint
    partial.demand_evidence = []
    partial.competition_evidence = []
    partial.trend_evidence = []
    partial.marketing_angles = []

    class Provider:
        def research(self, product, progress=None):
            raise ResearchProviderError(
                "API quota prevented classification", partial_report=partial
            )

    result = EvidenceResearchService(
        repo, api_key="test-secret", provider=Provider()
    ).research_product(product, force=True)
    assert result.status == "failed" and len(result.sources) == 3
    assert len(ProductRepository(repo.path).get_research(product.id).sources) == 3
