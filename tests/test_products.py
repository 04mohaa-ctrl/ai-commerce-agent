import pytest


def test_seed_is_diverse_valid_estimated_and_has_twelve_unique_products():
    from src.sources.local import LocalProductSource

    products = LocalProductSource().search("")
    assert len(products) >= 10
    assert len({p.id for p in products}) == len(products)
    assert len({p.category for p in products}) >= 5
    assert all(p.source == "demo" and p.evidence == [] for p in products)


@pytest.mark.parametrize(
    "query",
    [" PET PRODUCTS ", "pet accessories", "home fitness", "car accessories", "kitchen gadgets"],
)
def test_source_search_matches_category_and_tags_case_insensitively(query):
    from src.sources.local import LocalProductSource

    assert LocalProductSource().search(query)


def test_source_no_matches_returns_empty_list():
    from src.sources.local import LocalProductSource

    assert LocalProductSource().search("unobtainium telescope") == []


def test_filtering_and_numeric_sorting_do_not_mutate_results(result):
    from src.services.product_service import filter_results

    weak = result.model_copy(deep=True)
    weak.product = result.product.model_copy(update={"name": "Weak", "category": "Office"})
    weak.score.total = 20
    weak.gross_margin = 10
    weak.assessment.competition = 9
    rows = [weak, result]
    assert filter_results(rows, sort_by="AI Score")[0].product.name == "Pet Hair Remover"
    assert filter_results(rows, sort_by="Competition", descending=False)[0] == result
    assert filter_results(rows, categories=["Pet products"], min_score=60, min_margin=50) == [
        result
    ]
    assert filter_results(rows, min_score=100) == []
    assert rows[0] == weak


@pytest.mark.parametrize("sort_by", ["Margin", "Demand", "Trend", "Competition"])
def test_each_sort_key_uses_the_corresponding_numeric_value(result, sort_by):
    from src.services.product_service import filter_results

    lower = result.model_copy(deep=True)
    lower.product.name = "Lower"
    if sort_by == "Margin":
        lower.gross_margin = 1
    else:
        setattr(lower.assessment, sort_by.lower(), 1)
    assert filter_results([lower, result], sort_by=sort_by)[0] == result


def test_service_search_includes_durable_manual_candidates(tmp_path, product):
    from src.agents.product_research_agent import ProductResearchAgent
    from src.database.database import ProductRepository
    from src.services.product_service import ResearchService

    repo = ProductRepository(tmp_path / "research.db")
    repo.add_candidate(product.model_copy(update={"name": "Unique test roller"}))
    service = ResearchService(repo, ProductResearchAgent(api_key=""))
    rows = service.research("Unique test roller")
    assert len(rows) == 1
    assert rows[0].product.name == "Unique test roller"
    assert rows[0].mode == "demo"


def test_additional_source_can_be_plugged_in_without_changing_agent(tmp_path, product):
    from src.agents.product_research_agent import ProductResearchAgent
    from src.database.database import ProductRepository
    from src.services.product_service import ResearchService

    class FutureSource:
        def search(self, query):
            return [product] if query == "external" else []

    service = ResearchService(
        ProductRepository(tmp_path / "research.db"),
        ProductResearchAgent(api_key=""),
        sources=[FutureSource()],
    )
    assert service.research("external")[0].product == product


def test_settings_reads_dotenv_but_environment_takes_precedence(tmp_path, monkeypatch):
    from src.config import load_settings

    path = tmp_path / ".env"
    path.write_text(
        "OPENAI_API_KEY=file-secret\nOPENAI_MODEL=file-model\nDATABASE_PATH=data/test.db\n"
    )
    monkeypatch.setenv("OPENAI_API_KEY", "env-secret")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    settings = load_settings(path)
    assert settings.api_key == "env-secret"
    assert settings.model == "file-model"
    assert settings.database_path.is_absolute()
    assert "env-secret" not in repr(settings)


def test_manual_override_never_resurrects_old_seed_estimates_in_tag_search(tmp_path):
    from src.agents.product_research_agent import ProductResearchAgent
    from src.database.database import ProductRepository
    from src.schemas.product import Product
    from src.services.product_service import ResearchService

    repo = ProductRepository(tmp_path / "research.db")
    updated = Product(
        name="Pet Hair Remover",
        category="Pet products",
        cost=15,
        selling_price=20,
        description="My revised product",
    )
    repo.add_candidate(updated)
    service = ResearchService(repo, ProductResearchAgent(force_demo=True))
    assert service.candidates("Pet Hair Remover")[0].cost == 15
    # The replacement does not match this tag; an obsolete seed must not reappear.
    assert all(p.id != updated.id for p in service.candidates("pet accessories"))
