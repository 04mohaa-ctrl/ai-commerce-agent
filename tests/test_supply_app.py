from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app.py"


def test_supply_display_scale_matches_raw_dimensions_without_changing_stored_score():
    def view():
        from src.supply.models import Destination, SupplierMatch, SupplierOffer, SupplierSelection
        from src.supply.scoring import score_supply
        from src.ui.supplier_intelligence import _score_view
        from tests.test_supply_economics import NOW, selection
        from tests.test_supply_scoring import finance

        original = selection()
        chosen = SupplierSelection(
            offer=SupplierOffer(
                candidate=original.offer.candidate,
                variant=original.offer.variant,
                stock=original.offer.stock,
                quote=original.offer.quote,
                match=SupplierMatch(outcome="LIKELY_MATCH"),
            ),
            confirmed_attributes=dict(original.offer.variant.attributes),
            selected_at=NOW,
        )
        score = score_supply(
            chosen, Destination(quantity=2), finance(import_duty_per_unit=None), [], now=NOW
        )
        before = score.model_dump_json()
        _score_view(score)
        assert score.final_score == 77.5
        assert score.model_dump_json() == before

    app = AppTest.from_function(view, default_timeout=30).run()
    assert not app.exception
    assert any("Score: 7.75 / 10" in m.value and "coverage 85%" in m.value for m in app.markdown)
    assert any("Raw total 7.75 / 10" in c.value for c in app.caption)
    table = app.dataframe[0].value
    assert table.loc[0, "Raw /10"] == 7
    assert table.loc[0, "Contribution /10"] == 1.75
    assert table["Contribution /10"].sum() == 7.75


def test_market_display_labels_its_distinct_hundred_point_scale():
    def view():
        from src.supply.models import Destination
        from src.supply.scoring import score_opportunity
        from src.ui.supplier_intelligence import _score_view
        from tests.test_supply_economics import NOW, selection
        from tests.test_supply_scoring import finance, market

        _score_view(
            score_opportunity(
                market(), selection(), Destination(quantity=2), finance(), [], now=NOW
            )
        )

    app = AppTest.from_function(view, default_timeout=30).run()
    assert not app.exception
    assert any("Score:" in m.value and " / 100" in m.value for m in app.markdown)
    assert "Contribution /100" in app.dataframe[0].value.columns


@pytest.mark.parametrize(
    "notice,label,source",
    [
        (
            "CJ action research budget exhausted.",
            "Local action budget exhausted",
            "LOCAL_ACTION_BUDGET",
        ),
        ("CJ rate limit reached.", "Provider rate/quota limited", "PROVIDER_RATE_LIMIT"),
        ("Historical limit without origin", "Rate limited (origin unavailable)", None),
    ],
)
def test_historical_limit_status_and_telemetry_are_distinguished_without_db_writes(
    tmp_path, monkeypatch, product, notice, label, source
):
    import json

    from src.agents.product_research_agent import ProductResearchAgent
    from src.database.database import ProductRepository
    from src.database.supply_repository import SupplyRepository
    from src.supply.models import Destination, ProviderOutcome
    from src.supply.service import SupplierIntelligenceService
    from tests.test_supply_pipeline import FixtureSupplier

    path = tmp_path / "limits-ui.db"
    monkeypatch.setenv("DATABASE_PATH", str(path))
    monkeypatch.setenv("OPENAI_API_KEY", "")
    repo = ProductRepository(path)
    repo.save(ProductResearchAgent(force_demo=True).analyze(product))
    extension = SupplyRepository(repo, backup_dir=tmp_path / "backup")
    provider = FixtureSupplier(product)
    provider.name = "cj"
    provider.search = lambda query, **kwargs: ProviderOutcome(status="RATE_LIMITED", notice=notice)
    report = SupplierIntelligenceService(extension, provider).research(product, Destination())
    # Preserve an actual pre-fix payload, without a limit_source field.
    for stage in report.stages + report.telemetry.stages:
        if stage["component"] == "search":
            stage["status"] = "RATE_LIMITED"
            stage.pop("limit_source", None)
    extension.save_report(report)
    before = extension.get_report(product.id).model_dump_json()
    before_action = extension.get_latest_action(product.id).model_dump_json()
    monkeypatch.setattr("src.supply.service.CJDropShippingProvider", lambda: provider)
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.sidebar.radio("nav").set_value("Saved Products").run()
    assert not app.exception
    assert any(label in m.value for m in app.markdown)
    shown = [json.loads(item.value) for item in app.json]
    stages = [s for item in shown for s in item.get("stages", []) if s.get("component") == "search"]
    assert stages and all(s.get("limit_source") == source for s in stages)
    if source == "LOCAL_ACTION_BUDGET":
        assert all(s["status"] == "BUDGET_EXHAUSTED" for s in stages)
    else:
        assert all(s["status"] == "RATE_LIMITED" for s in stages)
    assert extension.get_report(product.id).model_dump_json() == before
    assert extension.get_latest_action(product.id).model_dump_json() == before_action
    assert provider.calls == []


def button(app, label):
    return next(b for b in app.button if b.label == label)


def test_keyless_supplier_view_does_not_activate_schema4(tmp_path, monkeypatch):
    import sqlite3

    path = tmp_path / "ui.db"
    monkeypatch.setenv("DATABASE_PATH", str(path))
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.delenv("CJ_API_KEY", raising=False)
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not app.exception
    assert "Supplier Intelligence" in [tab.label for tab in app.tabs]
    assert any("Live supplier data unavailable" in i.value for i in app.info)
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2


def test_supplier_selection_and_v4_financial_form_are_local_only(tmp_path, monkeypatch, product):
    from src.database.database import ProductRepository
    from src.database.supply_repository import SupplyRepository
    from src.supply.models import Destination
    from src.supply.service import SupplierIntelligenceService
    from tests.test_supply_pipeline import FixtureSupplier

    path = tmp_path / "saved-ui.db"
    monkeypatch.setenv("DATABASE_PATH", str(path))
    monkeypatch.setenv("OPENAI_API_KEY", "")
    repo = ProductRepository(path)
    from src.schemas.product import Assessment
    from src.services.scoring import build_result

    repo.save(build_result(product, Assessment(demand=5, competition=5, trend=5, marketing=5)))
    provider = FixtureSupplier(product)
    service = SupplierIntelligenceService(
        SupplyRepository(repo, backup_dir=tmp_path / "backup"), provider
    )
    service.research(product, Destination())
    monkeypatch.setattr("src.supply.service.CJDropShippingProvider", lambda: provider)
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.sidebar.radio("nav").set_value("Saved Products").run()
    calls = list(provider.calls)
    select = next(b for b in app.button if b.label == "Select this offer")
    select.click().run()
    assert not app.exception
    assert provider.calls == calls
    assert SupplyRepository(repo).get_selection(product.id).offer.variant.variant_id == "vid1"
    assert any("V4 ECONOMICS" in x.value for x in app.markdown)
    button(app, "Apply observed supplier cost").click().run()
    assert app.number_input(f"v4_econ_{product.id}_unit_product_cost").value == 5
    app.sidebar.radio("nav").set_value("Settings").run()
    app.sidebar.radio("nav").set_value("Saved Products").run()
    assert app.number_input(f"v4_econ_{product.id}_unit_product_cost").value == 5
    assert provider.calls == calls


def test_optional_provider_can_enable_research_without_openai(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "optional.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("CJ_API_KEY", "fixture-key-not-live")
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.sidebar.radio("nav").set_value("Settings").run()
    assert not app.toggle("demo_mode").disabled
    app.toggle("demo_mode").set_value(False).run()
    app.sidebar.radio("nav").set_value("Dashboard").run()
    assert app.session_state["use_demo"] is False


def test_main_research_uses_shared_supplier_action_without_openai(tmp_path, monkeypatch):
    from src.schemas.product import Product
    from tests.test_supply_pipeline import FixtureSupplier

    product = Product(name="Electric heated lunch box", category="Other", source="manual")
    provider = FixtureSupplier(product)
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "entry.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("CJ_API_KEY", "fixture-key-not-live")
    monkeypatch.setattr("src.supply.service.CJDropShippingProvider", lambda: provider)
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.sidebar.radio("nav").set_value("Settings").run()
    app.toggle("demo_mode").set_value(False).run()
    app.sidebar.radio("nav").set_value("Research").run()
    app.text_input("research_query").set_value(product.name)
    app.selectbox("v4_target_country").set_value("SE")
    app.number_input("v4_target_quantity").set_value(3)
    button(app, "Find / Analyze Products").click().run()
    button(app, "Research this product").click().run()
    assert not app.exception
    assert provider.calls == ["search", "details", "variants", "stock"]
    from src.database.database import ProductRepository
    from src.database.supply_repository import SupplyRepository

    repo = ProductRepository(tmp_path / "entry.db")
    saved = repo.list_candidates()
    candidate = next(p for p in saved if p.name == product.name)
    report = SupplyRepository(repo).get_report(candidate.id)
    assert report.destination.country == "SE"
    assert report.destination.quantity == 3


def test_first_manual_v4_save_preserves_submitted_unknown_and_zero_inputs(
    tmp_path, monkeypatch, product
):
    from src.agents.product_research_agent import ProductResearchAgent
    from src.database.database import ProductRepository
    from src.database.supply_repository import SupplyRepository

    path = tmp_path / "first-save.db"
    monkeypatch.setenv("DATABASE_PATH", str(path))
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.delenv("CJ_API_KEY", raising=False)
    product = product.model_copy(update={"cost": None, "selling_price": None})
    repo = ProductRepository(path)
    repo.save(ProductResearchAgent(force_demo=True).analyze(product))
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.sidebar.radio("nav").set_value("Saved Products").run()
    app.number_input(f"v4_econ_{product.id}_unit_product_cost").set_value(17.5)
    app.number_input(f"v4_econ_{product.id}_packaging_per_unit").set_value(0)
    button(app, "Save V4 economics assumptions").click().run()
    assert not app.exception
    saved = SupplyRepository(repo).get_financial(product.id)
    assert saved.inputs.unit_product_cost == 17.5
    assert saved.inputs.packaging_per_unit == 0
    assert saved.inputs.customs_fee_per_unit is None
    assert saved.provenance["packaging_per_unit"].source_kind == "ESTIMATED"


def test_multiple_methods_and_warehouses_have_distinct_widgets(tmp_path, monkeypatch, product):
    from src.agents.product_research_agent import ProductResearchAgent
    from src.database.database import ProductRepository
    from src.database.supply_repository import SupplyRepository
    from src.supply.models import Destination, ShippingQuote
    from src.supply.service import SupplierIntelligenceService
    from tests.test_supply_pipeline import FixtureSupplier

    path = tmp_path / "multiple-ui.db"
    monkeypatch.setenv("DATABASE_PATH", str(path))
    monkeypatch.setenv("OPENAI_API_KEY", "")
    repo = ProductRepository(path)
    repo.save(ProductResearchAgent(force_demo=True).analyze(product))
    extension = SupplyRepository(repo, backup_dir=tmp_path / "backup")
    provider = FixtureSupplier(product)
    report = SupplierIntelligenceService(extension, provider).research(product, Destination())
    offer = report.offers[0]
    quote = ShippingQuote.model_validate(
        provider.shipping(offer.variant, offer.stock, Destination()).records[0]
    )
    report.offers = [
        offer.model_copy(update={"quote": quote}),
        offer.model_copy(update={"quote": quote.model_copy(update={"method": "Express"})}),
        offer.model_copy(
            update={
                "stock": offer.stock.model_copy(
                    update={"warehouse_id": "area2", "storage_id": "sub2"}
                )
            }
        ),
    ]
    extension.save_report(report)
    monkeypatch.setattr("src.supply.service.CJDropShippingProvider", lambda: provider)
    calls = list(provider.calls)
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.sidebar.radio("nav").set_value("Saved Products").run()
    selects = [b for b in app.button if b.label == "Select this offer"]
    assert len(selects) == 3 and len({b.key for b in selects}) == 3
    assert not app.exception
    selects[2].click().run()
    assert not app.exception
    assert extension.get_selection(product.id).offer.stock.storage_id == "sub2"
    assert provider.calls == calls
