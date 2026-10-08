"""Offline replay of released V4 observations; source times and identities stay intact."""

import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src.agents.product_research_agent import ProductResearchAgent
from src.database.database import ProductRepository
from src.database.supply_repository import SupplyRepository
from src.research.providers.base import product_fingerprint
from src.schemas.product import Product
from src.supply.economics import supplier_cost_issue, utc_now
from src.supply.matching import candidate_viable, match_supplier
from src.supply.models import Destination, SupplierOffer, SupplyIntelligenceReport
from src.supply.service import SupplierIntelligenceService

APP = Path(__file__).resolve().parents[1] / "app.py"
FIXTURE = Path(__file__).parent / "fixtures" / "v4_laptop_stand.json"


@pytest.fixture
def saved_case():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return (
        Product.model_validate(data["product"]),
        Destination.model_validate(data["destination"]),
        [SupplierOffer.model_validate(o) for o in data["offers"]],
        data,
    )


@pytest.mark.parametrize(
    "requirement,index,outcome,missing",
    [
        ("", 0, "AMBIGUOUS", ["color"]),
        ("Black", 0, "MATCH", []),
        ("White", 0, "NO_MATCH", []),
        ("Black", 1, "NO_MATCH", []),
    ],
)
def test_saved_stand_requires_comparable_target_color(
    saved_case, requirement, index, outcome, missing
):
    product, destination, offers, _ = saved_case
    if requirement:
        product = product.model_copy(
            update={"description": product.description + f"\nColor: {requirement}"}
        )
    offer = offers[index]
    result = match_supplier(product, offer.candidate, offer.variant, destination)
    assert result.outcome == outcome
    assert result.missing_attributes == missing
    if outcome == "NO_MATCH":
        assert any("color" in c for c in result.contradictions)


@pytest.mark.parametrize("requirement", ["", "Black", "White"])
def test_phone_side_mount_is_rejected_even_when_color_matches(saved_case, requirement):
    product, destination, offers, _ = saved_case
    product = product.model_copy(
        update={"description": product.description + f"\nColor: {requirement}"}
    )
    offer = offers[2]
    assert (
        match_supplier(product, offer.candidate, offer.variant, destination).outcome == "NO_MATCH"
    )
    assert not candidate_viable(product, offer.candidate)


def test_stand_with_optional_phone_holder_is_not_the_side_mount_accessory(saved_case):
    product, destination, offers, _ = saved_case
    product = product.model_copy(update={"description": "Color: Black"})
    candidate = offers[0].candidate.model_copy(
        update={"name": "Foldable laptop stand with phone holder"}
    )
    assert candidate_viable(product, candidate)
    assert (
        match_supplier(product, candidate, offers[0].variant, destination).outcome == "LIKELY_MATCH"
    )


def button(app, label):
    return next(b for b in app.button if b.label == label)


@pytest.mark.parametrize("description", ["Color: White", ""])
def test_changed_requirements_cannot_refresh_shipping_with_historical_selection(
    tmp_path, saved_case, description
):
    from src.supply.models import SupplierSelection
    from tests.test_supply_pipeline import FixtureSupplier

    product, destination, offers, _ = saved_case
    product = product.model_copy(update={"description": "Color: Black"})
    offer = offers[0].model_copy(
        update={
            "match": match_supplier(product, offers[0].candidate, offers[0].variant, destination)
        }
    )
    repo = SupplyRepository(ProductRepository(tmp_path / "shipping.db"), tmp_path / "backup")
    repo.save_report(
        SupplyIntelligenceReport(
            product_id=product.id,
            input_fingerprint=product_fingerprint(product),
            destination=destination,
            offers=[offer],
        )
    )
    repo.save_selection(product.id, SupplierSelection(offer=offer))
    provider = FixtureSupplier(product)
    service = SupplierIntelligenceService(repo, provider)
    changed = product.model_copy(update={"description": description})
    service.recheck_saved(changed, destination)
    report = service.refresh_shipping(changed, destination)
    assert provider.calls == [], "An incompatible historical selection must not request freight"
    assert report.stages[-1]["status"] == "UNAVAILABLE"


def test_saved_ui_requirements_recheck_selection_and_explicit_adoption(
    tmp_path, monkeypatch, saved_case
):
    import httpx

    def no_requests(*args, **kwargs):
        pytest.fail("This workflow must not dispatch any provider requests")

    monkeypatch.setattr(httpx.Client, "send", no_requests)
    monkeypatch.setattr(httpx.AsyncClient, "send", no_requests)
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.delenv("CJ_API_KEY", raising=False)
    path = tmp_path / "ui.db"
    monkeypatch.setenv("DATABASE_PATH", str(path))
    product, destination, offers, data = saved_case
    now = datetime.fromisoformat(data["researched_at"]) + timedelta(minutes=5)
    monkeypatch.setattr("src.ui.supplier_intelligence.utc_now", lambda: now)
    monkeypatch.setattr("src.supply.economics.utc_now", lambda: now)
    repo = ProductRepository(path)
    repo.save(ProductResearchAgent(force_demo=True).analyze(product))
    repo.add_candidate(product)
    extension = SupplyRepository(repo, backup_dir=tmp_path / "backup")
    extension.save_settings(product.id, destination)
    extension.save_report(
        SupplyIntelligenceReport(
            product_id=product.id,
            input_fingerprint=product_fingerprint(product),
            destination=destination,
            offers=offers,
            stages=data["stages"],
            researched_at=data["researched_at"],
        )
    )
    extension.save_shortlist(product.id, offers[0], "Preferred", "This one")
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.sidebar.radio("nav").set_value("Saved Products").run()
    assert not app.exception
    assert all(b.disabled for b in app.button if b.label == "Select this offer")
    assert extension.get_selection(product.id) is None
    assert any("Preferred" in m.value and "This one" in m.value for m in app.markdown)

    editor = [t for t in app.text_area if t.label == "Target description / variant requirements"]
    assert len(editor) == 1, "Saved products need a visible target requirements editor"
    editor[0].set_value(product.description + "\nColor: Black")
    button(app, "Save target requirements and recheck saved offers").click().run()
    assert not app.exception
    selects = [b for b in app.button if b.label == "Select this offer"]
    assert [b.disabled for b in selects] == [False, True, True]
    updated = extension.get_report(product.id)
    assert updated.offers[0].variant.id == offers[0].variant.id
    assert updated.offers[0].stock.id == offers[0].stock.id
    assert updated.researched_at == datetime.fromisoformat(data["researched_at"])
    assert extension.get_selection(product.id) is None
    assert extension.get_financial(product.id) is None
    assert extension.get_shortlist(product.id)[0]["offer"] == offers[0].model_dump(mode="json")
    assert repo.list_candidates()[0].description.endswith("Color: Black")
    selects[0].click().run()
    assert not app.exception
    chosen = extension.get_selection(product.id)
    assert chosen.offer.variant.variant_id == "1CC71DF3-9C07-43FD-9B78-074266306AD0"
    assert chosen.offer.stock.storage_id == "{6709CCD7-0DC7-43B1-B310-17AB499E9B0A}"
    assert extension.get_financial(product.id) is None
    assert app.number_input(f"v4_econ_{product.id}_unit_product_cost").value == 8.9
    button(app, "Apply observed supplier cost").click().run()
    assert not app.exception
    adopted = extension.get_financial(product.id)
    assert adopted.inputs.unit_product_cost == 3.1
    assert adopted.provenance["unit_product_cost"].value == Decimal("3.1")
    assert adopted.provenance["unit_product_cost"].observation_id == offers[0].variant.id
    # Original timestamps remain authoritative: stale prices cannot be adopted.
    stale = chosen.model_copy(
        update={
            "offer": chosen.offer.model_copy(
                update={
                    "variant": chosen.offer.variant.model_copy(
                        update={"observed_at": utc_now().replace(year=2020)}
                    )
                }
            )
        }
    )
    assert "stale" in supplier_cost_issue(stale, "USD", utc_now())

    app.text_area(editor[0].key).set_value(product.description + "\nColor: White")
    button(app, "Save target requirements and recheck saved offers").click().run()
    assert not app.exception
    assert all(b.disabled for b in app.button if b.label == "Select this offer")
    assert button(app, "Apply observed supplier cost").disabled
    assert extension.get_selection(product.id).id == chosen.id
    assert extension.get_financial(product.id).model_dump_json() == adopted.model_dump_json()
    # Blank is still unknown, and reopening restores the user's saved requirements.
    app.text_area(editor[0].key).set_value(product.description)
    button(app, "Save target requirements and recheck saved offers").click().run()
    reopened = AppTest.from_file(str(APP), default_timeout=30).run()
    reopened.sidebar.radio("nav").set_value("Saved Products").run()
    assert not reopened.exception
    assert reopened.text_area(editor[0].key).value == product.description
    assert all(b.disabled for b in reopened.button if b.label == "Select this offer")
