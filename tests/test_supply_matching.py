"""Conservative supplier matching with normalized, explicit variant attributes."""

import pytest

from src.schemas.product import Product
from src.supply.matching import destination_issue, match_supplier
from src.supply.models import Destination, SupplierProductCandidate, SupplierVariant


def match(name, listing=None, description="", attributes=None, country="US", brand=None):
    candidate = SupplierProductCandidate(
        provider="cj", product_id="p1", name=listing or name, brand=brand
    )
    variant = SupplierVariant(
        provider="cj",
        product_id="p1",
        variant_id="v1",
        name=listing or name,
        attributes=attributes or {},
    )
    return match_supplier(
        Product(name=name, category="Home", description=description),
        candidate,
        variant,
        Destination(country=country),
    )


def test_exact_name_match_and_related_name_review_remain_distinct():
    assert match("Reusable lunch box").outcome == "MATCH"
    assert match("Reusable lunch box", "Premium reusable lunch box").outcome == "LIKELY_MATCH"
    assert match("Reusable lunch box", "Wireless gaming headphones").outcome == "NO_MATCH"


@pytest.mark.parametrize(
    "description,attributes,field",
    [
        ("Brand: Acme", {"brand": "Other"}, "brand"),
        ("Model: X100", {"model": "X200"}, "model"),
        ("Capacity: 500ml", {"capacity": "1L"}, "capacity"),
        ("Count: 2", {"count": "3"}, "count"),
        ("Dimensions: 10cm", {"dimensions": "200mm"}, "dimensions"),
    ],
)
def test_explicit_variant_contradictions_override_name_similarity(description, attributes, field):
    result = match("Reusable lunch box", description=description, attributes=attributes)
    assert result.outcome == "NO_MATCH"
    assert any(field in reason.lower() for reason in result.contradictions)


@pytest.mark.parametrize(
    "attributes,field",
    [
        ({"voltage": "220V", "plug": "US"}, "voltage"),
        ({"voltage": "110V", "plug": "EU"}, "plug"),
    ],
)
def test_destination_electrical_contradictions_are_rejected(attributes, field):
    result = match("Electric heated lunch box", attributes=attributes)
    assert result.outcome == "NO_MATCH"
    assert any(field in reason.lower() for reason in result.contradictions)


@pytest.mark.parametrize(
    "country,voltage,plug",
    [
        ("US", "110-120V", "US"),
        ("US", "100-240 V", "Type A"),
        ("SE", "220-240V", "EU"),
        ("DE", "230V", "Type F"),
        ("FR", "230V", "Type E"),
        ("GB", "230V", "Type G"),
    ],
)
def test_observed_compatible_electrical_attributes_allow_identity_match(country, voltage, plug):
    assert (
        match(
            "Electric heated lunch box",
            attributes={"voltage": voltage, "plug": plug},
            country=country,
        ).outcome
        == "MATCH"
    )


@pytest.mark.parametrize(
    "attributes,missing",
    [
        ({}, {"voltage", "plug"}),
        ({"voltage": "110V"}, {"plug"}),
        ({"plug": "US"}, {"voltage"}),
        ({"voltage": "unknown", "plug": "unknown"}, {"voltage", "plug"}),
    ],
)
def test_missing_decisive_electrical_attributes_are_ambiguous(attributes, missing):
    result = match("Electric heated lunch box", attributes=attributes)
    assert result.outcome == "AMBIGUOUS"
    assert missing.issubset(result.missing_attributes)


@pytest.mark.parametrize(
    "name,listing",
    [
        ("Reusable lunch box 500ml", "Reusable lunch box 0.5L"),
        ("Reusable lunch box 10cm", "Reusable lunch box 100mm"),
        ("Reusable lunch box 1kg", "Reusable lunch box 1000g"),
        ("Reusable lunch box 2 pieces", "Reusable lunch box 2 pack"),
    ],
)
def test_unit_equivalence_does_not_create_false_contradictions(name, listing):
    assert match(name, listing).outcome == "MATCH"


def test_equivalent_explicit_capacity_and_dimensions_attributes_match():
    result = match(
        "Reusable lunch box",
        description="Capacity: 500ml; Dimensions: 10cm",
        attributes={"capacity": "0.5L", "dimensions": "100mm"},
    )
    assert result.outcome == "MATCH"


def test_candidate_brand_and_variant_brand_conflict_cannot_be_hidden():
    result = match(
        "Reusable lunch box", description="Brand: Acme", brand="Acme", attributes={"brand": "Other"}
    )
    assert result.outcome == "NO_MATCH"


def test_conflicting_electrical_values_in_variant_name_are_not_overridden():
    result = match(
        "Electric heated lunch box",
        listing="Electric heated lunch box 220V EU plug",
        attributes={"voltage": "110V", "plug": "US"},
    )
    assert result.outcome == "NO_MATCH"


def test_missing_expected_model_is_ambiguous_even_with_exact_name():
    result = match("Reusable lunch box", description="Model: X100")
    assert result.outcome == "AMBIGUOUS"
    assert "model" in result.missing_attributes


def test_explicit_attribute_values_can_supply_missing_name_discriminators():
    result = match(
        "Reusable lunch box 500ml", listing="Reusable lunch box", attributes={"capacity": "0.5L"}
    )
    assert result.outcome == "MATCH"


def test_different_expected_count_rejects_supplier_bundle():
    result = match(
        "Reusable lunch box 2 pack", listing="Reusable lunch box", attributes={"count": "1"}
    )
    assert result.outcome == "NO_MATCH"


def test_models_in_names_are_explicit_discriminators():
    result = match("Reusable lunch box X100", "Reusable lunch box X200")
    assert result.outcome == "NO_MATCH"
    assert any("model" in reason for reason in result.contradictions)


def test_multi_axis_dimensions_are_normalized_as_one_shape():
    assert (
        match("Reusable lunch box 10x20x30cm", "Reusable lunch box 100x200x300mm").outcome
        == "MATCH"
    )
    assert (
        match("Reusable lunch box 10x20x30cm", "Reusable lunch box 100x200x400mm").outcome
        == "NO_MATCH"
    )


def test_unknown_destination_electrical_rules_remain_ambiguous():
    result = match(
        "Electric heated lunch box", attributes={"voltage": "110V", "plug": "US"}, country="ZZ"
    )
    assert result.outcome == "AMBIGUOUS"
    assert "destination electrical suitability" in result.missing_attributes


def test_option_only_variant_name_uses_product_identity_and_explicit_facts():
    product = Product(name="Electric heated lunch box", category="Home")
    candidate = SupplierProductCandidate(provider="cj", product_id="p1", name=product.name)
    variant = SupplierVariant(
        provider="cj",
        product_id="p1",
        variant_id="v1",
        name="US plug 110V",
        attributes={"plug": "US", "voltage": "110V"},
    )
    assert match_supplier(product, candidate, variant, Destination()).outcome == "MATCH"


def test_selected_electrical_offer_cannot_be_applied_to_changed_destination():
    candidate = SupplierProductCandidate(
        provider="cj", product_id="p1", name="Electric heated lunch box"
    )
    variant = SupplierVariant(
        provider="cj",
        product_id="p1",
        variant_id="v1",
        name=candidate.name,
        attributes={"voltage": "120V", "plug": "US"},
    )
    assert destination_issue(candidate, variant, Destination()) is None
    assert destination_issue(candidate, variant, Destination(country="SE")) is not None
    assert (
        destination_issue(candidate, variant.model_copy(update={"attributes": {}}), Destination())
        is not None
    )


def test_passive_selected_offer_has_no_electrical_destination_requirement():
    candidate = SupplierProductCandidate(provider="cj", product_id="p1", name="Reusable lunch box")
    variant = SupplierVariant(provider="cj", product_id="p1", variant_id="v1", name=candidate.name)
    assert destination_issue(candidate, variant, Destination(country="SE")) is None


def test_documented_composite_variant_key_supplies_observed_electrical_facts():
    assert (
        match("Electric heated lunch box", attributes={"variant_key": "US Plug-110V"}).outcome
        == "MATCH"
    )
    rejected = match("Electric heated lunch box", attributes={"variant_key": "EU Plug-230V"})
    assert rejected.outcome == "NO_MATCH"
    assert any("voltage" in reason for reason in rejected.contradictions)
