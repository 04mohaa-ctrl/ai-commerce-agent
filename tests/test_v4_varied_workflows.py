"""Varied synthetic negative cases plus captured genuine stand freight, no live calls."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from src.database.database import ProductRepository
from src.database.supply_repository import SupplyRepository
from src.research.providers.base import product_fingerprint
from src.schemas.product import Product
from src.supply.economics import selection_issue, shipping_issue, stock_issue
from src.supply.models import (
    Destination,
    ShippingQuote,
    SupplierMatch,
    SupplierOffer,
    SupplierProductCandidate,
    SupplierSelection,
    SupplierVariant,
    SupplyIntelligenceReport,
)
from src.supply.service import SupplierIntelligenceService
from tests.test_supply_economics import NOW


@pytest.mark.parametrize(
    "name,listing,attributes,outcome",
    [
        (
            "Electric heated lunch box",
            "Electric heated lunch box",
            {"voltage": "120V", "plug": "US"},
            "NO_MATCH",
        ),
        ("Foldable Laptop Stand", "Laptop phone side-mount holder", {"color": "Black"}, "NO_MATCH"),
        ("Pet Hair Remover", "Pet Hair Remover", {}, "MATCH"),
    ],
)
def test_varied_saved_requirements_recheck_selection_and_missing_supply(
    tmp_path, name, listing, attributes, outcome
):
    product = Product(name=name, category="Home")
    dest = Destination(country="SE")
    ext = SupplyRepository(ProductRepository(tmp_path / "case.db"))
    candidate = SupplierProductCandidate(
        provider="fixture", product_id="fixture-case", name=listing, observed_at=NOW
    )
    variant = SupplierVariant(
        provider="fixture",
        product_id="fixture-case",
        variant_id="fixture-variant",
        name=listing,
        attributes=attributes,
        unit_price=3,
        currency="USD",
        observed_at=NOW,
    )
    offer = SupplierOffer(
        candidate=candidate, variant=variant, match=SupplierMatch(outcome="AMBIGUOUS")
    )
    ext.save_report(
        SupplyIntelligenceReport(
            product_id=product.id,
            input_fingerprint=product_fingerprint(product),
            destination=dest,
            offers=[offer],
        )
    )
    service = SupplierIntelligenceService(ext)
    report = service.recheck_saved(product, dest)
    assert report.offers[0].match.outcome == outcome
    assert report.offers[0].variant.id == variant.id
    assert not report.telemetry.requests
    reopened = SupplyRepository(ProductRepository(ext.path)).get_report(product.id)
    assert reopened.offers[0].match.outcome == outcome
    if outcome == "NO_MATCH":
        with pytest.raises(ValueError):
            SupplierSelection(offer=report.offers[0])
    else:
        chosen = SupplierSelection(offer=report.offers[0], selected_at=NOW)
        assert selection_issue(chosen, dest) is None
        assert stock_issue(chosen, dest, NOW) is not None
        assert shipping_issue(chosen, dest, "USD", NOW) is not None


def test_genuine_captured_freight_is_exact_and_distinct_from_synthetic_fixture(tmp_path):
    from tests.test_supply_workflow import seed

    product, ext, offers = seed(tmp_path / "captured.db")
    captured = json.loads(
        (Path(__file__).parent / "fixtures/v4_captured_live_freight.json").read_text()
    )
    quotes = [ShippingQuote.model_validate(q) for q in captured["quotes"]]
    quote = next(q for q in quotes if q.method == "CJPacket Eub Special Line")
    stand = SupplierOffer.model_validate(captured["supplier_offer"])
    assert quote.variant_snapshot == stand.variant.id
    assert quote.storage_id == stand.stock.storage_id
    assert quote.total_cost == Decimal("13.60")
    assert (quote.delivery_min_days, quote.delivery_max_days) == (8, 12)
    assert quote.tracking is None
    assert "genuine live" in captured["evidence"]
    synthetic = json.loads(
        (Path(__file__).parent / "fixtures/v4_freight_contract_response.json").read_text()
    )
    assert synthetic["response"]["data"][0]["logisticPrice"] != str(quote.total_cost)
