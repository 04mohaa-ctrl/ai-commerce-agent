"""Product-or-category entry reuses V2 evidence research and keeps costs unknown."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from tests.research_fixtures import report_fixture

APP = Path(__file__).resolve().parents[1] / "app.py"


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "entry.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "")


def start():
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    app.sidebar.radio("nav").set_value("Research").run()
    return app


def button(app, label):
    return next(b for b in app.button if b.label == label)


def search(app, query):
    app.text_input("research_query").set_value(query)
    button(app, "Find / Analyze Products").click().run()


def service(tmp_path):
    from src.agents.product_research_agent import ProductResearchAgent
    from src.database.database import ProductRepository
    from src.services.product_service import ResearchService

    repo = ProductRepository(tmp_path / "unit.db")
    return ResearchService(repo, ProductResearchAgent(force_demo=True)), repo


def test_exact_name_normalization_selects_existing_product(tmp_path):
    research, repo = service(tmp_path)
    matches = research.exact_products("  PORTABLE   BLENDER ")
    assert len(matches) == 1 and matches[0].name == "Portable Blender"
    selected = research.get_or_create_custom("portable blender")
    assert selected.id == matches[0].id
    assert selected.cost == 11
    assert repo.list_candidates() == []


def test_arbitrary_product_has_unknown_economics_and_reuses_canonical_name(tmp_path):
    from src.services.economics import EconomicsInputs, calculate_economics

    research, repo = service(tmp_path)
    a = research.get_or_create_custom("Electric heated lunch box")
    b = research.get_or_create_custom(" ELECTRIC   HEATED LUNCH BOX ")
    assert a.id == b.id and len(repo.list_candidates()) == 1
    assert a.cost is None and a.selling_price is None
    result = calculate_economics(
        EconomicsInputs(product_cost=a.cost, selling_price=a.selling_price)
    )
    assert result.gross_profit is None and result.estimated_net_profit is None
    assert result.break_even_ad_cost is None


def test_existing_product_from_main_input_runs_shared_flow_once(monkeypatch):
    from src.research.providers.web_research import WebResearchProvider

    calls = []

    def boundary(self, product, progress=None):
        calls.append(product.name)
        return report_fixture()

    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    monkeypatch.setattr(WebResearchProvider, "research", boundary)
    app = start()
    app.sidebar.radio("nav").set_value("Settings").run()
    app.toggle("demo_mode").set_value(False).run()
    app.sidebar.radio("nav").set_value("Research").run()
    search(app, "Pet Hair Remover")
    assert not app.exception
    assert calls == ["Pet Hair Remover"]
    assert len(app.dataframe[0].value) == 1
    assert any("Research completed" in x.value for x in app.success)
    assert not any(b.label == "Research this product" for b in app.button)


def test_new_name_offers_one_click_research_without_manual_form(monkeypatch):
    from src.research.providers.web_research import WebResearchProvider

    calls = []

    def boundary(self, product, progress=None):
        calls.append(product.name)
        return report_fixture()

    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    monkeypatch.setattr(WebResearchProvider, "research", boundary)
    app = start()
    app.sidebar.radio("nav").set_value("Settings").run()
    app.toggle("demo_mode").set_value(False).run()
    app.sidebar.radio("nav").set_value("Research").run()
    search(app, "Electric heated lunch box")
    assert calls == []  # Unmatched search does not create a product or spend an API call.
    button(app, "Research this product").click().run()
    assert not app.exception
    assert calls == ["Electric heated lunch box"]
    assert app.dataframe[0].value.iloc[0]["Product name"] == "Electric heated lunch box"
    assert app.number_input("econ_product_cost").value is None
    assert app.number_input("econ_selling_price").value is None
    assert any("https://publisher0.com/pet-hair" in x.value for x in app.markdown)
    button(app, "Save product").click().run()
    app.sidebar.radio("nav").set_value("Saved Products").run()
    assert app.metric[1].value == "1"
    assert any("https://publisher0.com/pet-hair" in x.value for x in app.markdown)


def test_broad_category_keeps_candidate_listing_and_does_not_create_custom():
    app = start()
    search(app, "Kitchen gadgets")
    assert not app.exception
    assert len(app.dataframe[0].value) == 3
    assert {"Portable Blender", "Silicone Air Fryer Liners"}.issubset(
        set(app.dataframe[0].value["Product name"])
    )
    assert not any(b.label == "Research this product" for b in app.button)
    assert any("No research performed" in x.value for x in app.info)


def test_no_results_offers_custom_action_and_blank_search_lists_all():
    app = start()
    search(app, "Unlisted travel accessory")
    assert any("No products match" in x.value for x in app.info)
    assert any(b.label == "Research this product" for b in app.button)
    search(app, " ")
    assert not app.exception
    assert len(app.dataframe[0].value) == 12
    assert not any(b.label == "Research this product" for b in app.button)


def test_duplicate_custom_product_keeps_persisted_economics_and_demo_mode():
    from src.config import load_settings
    from src.database.database import ProductRepository

    app = start()
    search(app, "Electric heated lunch box")
    button(app, "Research this product").click().run()
    assert not app.exception
    assert any("Demo Mode" in x.value for x in app.info)
    for field, value in [
        ("product_cost", 10),
        ("selling_price", 40),
        ("shipping_cost", 5),
        ("payment_fee_percent", 3),
        ("estimated_ad_cost_per_order", 8),
    ]:
        app.number_input("econ_" + field).set_value(value)
    button(app, "Save economics assumptions").click().run()
    search(app, " ELECTRIC   HEATED LUNCH BOX ")
    assert not app.exception
    assert app.number_input("econ_product_cost").value == 10
    assert app.number_input("econ_selling_price").value == 40
    repo = ProductRepository(load_settings().database_path)
    assert len(repo.list_candidates()) == 1
    assert repo.get_economics(repo.list_candidates()[0].id).shipping_cost == 5


def test_unknown_margin_sorts_and_filters_safely(tmp_path):
    from src.services.product_service import filter_results

    research, _ = service(tmp_path)
    research.get_or_create_custom("Electric heated lunch box")
    rows = research.research("")
    unknown = next(r for r in rows if r.product.name == "Electric heated lunch box")
    assert unknown.gross_margin is None and unknown.score.profit_potential == 0
    assert filter_results(rows, sort_by="Margin")[-1] == unknown
    assert filter_results(rows, sort_by="Margin", descending=False)[-1] == unknown
    assert unknown not in filter_results(rows, min_margin=0)


def test_direct_product_opens_details_even_after_excluding_filters():
    app = start()
    app.slider("minscore_research").set_value(100).run()
    search(app, "Portable Blender")
    assert not app.exception
    assert app.slider("minscore_research").value == 0
    assert any("Product details · Portable Blender" in x.value for x in app.subheader)
