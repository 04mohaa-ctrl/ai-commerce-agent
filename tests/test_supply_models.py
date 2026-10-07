"""Identity, safety and unknown-value contracts for V4 observations."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.supply.models import (
    ActionTelemetry,
    Destination,
    ProviderOutcome,
    ShippingQuote,
    StockObservation,
    SupplierMatch,
    SupplierOffer,
    SupplierProductCandidate,
    SupplierSelection,
    SupplierVariant,
    SupplyIntelligenceReport,
)

NOW = datetime(2026, 10, 7, tzinfo=timezone.utc)


def candidate(**changes):
    return SupplierProductCandidate.model_validate(
        {"provider": "cj", "product_id": "p1", "name": "Lunch box", "observed_at": NOW, **changes}
    )


def variant(**changes):
    return SupplierVariant.model_validate(
        {
            "provider": "cj",
            "product_id": "p1",
            "variant_id": "v1",
            "name": "Lunch box",
            "observed_at": NOW,
            **changes,
        }
    )


def stock(**changes):
    return StockObservation.model_validate(
        {
            "provider": "cj",
            "product_id": "p1",
            "variant_id": "v1",
            "warehouse_id": "w1",
            "storage_id": "s1",
            "country": "CN",
            "observed_at": NOW,
            **changes,
        }
    )


def quote(**changes):
    return ShippingQuote.model_validate(
        {
            "provider": "cj",
            "product_id": "p1",
            "variant_id": "v1",
            "warehouse_id": "w1",
            "storage_id": "s1",
            "origin": "CN",
            "destination": Destination(),
            "quantity": 1,
            "method": "Tracked",
            "observed_at": NOW,
            **changes,
        }
    )


def test_defaults_preserve_unknowns_and_explicit_zero():
    assert Destination().model_dump() == {
        "country": "US",
        "quantity": 1,
        "max_delivery_days": 14,
        "postal_code": "",
        "region": "",
    }
    assert variant().unit_price is None
    assert stock().quantity is None
    assert quote().total_cost is None
    assert quote().tracking is None
    assert variant(unit_price="0", currency="USD").unit_price == Decimal("0")
    assert stock(quantity=0, cj_quantity=0, factory_quantity=10).quantity == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("quantity", 0),
        ("quantity", True),
        ("quantity", "2"),
        ("max_delivery_days", 0),
        ("country", "USA"),
        ("postal_code", "a\nheader"),
    ],
)
def test_destination_rejects_invalid_request_parameters(field, value):
    with pytest.raises(ValidationError):
        Destination.model_validate({field: value})


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "http://example.com/x",
        "https://user:pass@example.com/x",
        "https://localhost/x",
        "https://127.0.0.1/x",
        "https://example.com/x?api_key=secret",
    ],
)
@pytest.mark.parametrize("field", ["source_url", "image_url"])
def test_observation_rejects_unsafe_links(field, url):
    with pytest.raises(ValidationError):
        candidate(**{field: url})


def test_links_canonicalize_without_tracking():
    assert candidate(source_url="https://EXAMPLE.com/p?utm_source=x&pid=1#frag").source_url == (
        "https://example.com/p?pid=1"
    )


@pytest.mark.parametrize("field,value", [("provider", " "), ("product_id", ""), ("product_id", 1)])
def test_observation_requires_strict_nonempty_identity(field, value):
    with pytest.raises(ValidationError):
        candidate(**{field: value})


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", True, float("inf")])
def test_nonfinite_negative_or_boolean_money_is_not_an_unknown_or_price(value):
    with pytest.raises(ValidationError):
        variant(unit_price=value, currency="USD")
    with pytest.raises(ValidationError):
        quote(total_cost=value, currency="USD")
    with pytest.raises(ValidationError):
        quote(taxes_fee=value, currency="USD")


def test_known_money_requires_currency():
    with pytest.raises(ValidationError):
        variant(unit_price="2")
    with pytest.raises(ValidationError):
        quote(total_cost="2")


@pytest.mark.parametrize("builder", [candidate, variant, stock, quote])
def test_observations_reject_naive_times_and_normalize_aware_times(builder):
    with pytest.raises(ValidationError):
        builder(observed_at=datetime(2026, 10, 7))
    observed = builder(observed_at=NOW.astimezone(timezone(timedelta(hours=2))))
    assert observed.observed_at == NOW
    assert observed.observed_at.utcoffset() == timedelta(0)


def test_observation_ids_are_immutable_content_and_time_bound_and_roundtrip():
    observed = variant(unit_price="1.20", currency="USD", attributes={"plug": "US"})
    payload = observed.model_dump(mode="json")
    assert payload["id"] == observed.id
    assert SupplierVariant.model_validate(payload).id == observed.id
    assert variant(unit_price="1.21", currency="USD").id != observed.id
    assert variant(observed_at=NOW + timedelta(seconds=1)).id != variant().id
    with pytest.raises(ValidationError):
        observed.unit_price = Decimal("7")
    with pytest.raises(TypeError):
        observed.attributes["plug"] = "EU"
    payload["unit_price"] = "8"
    with pytest.raises(ValidationError):
        SupplierVariant.model_validate(payload)


def test_offer_rejects_mixed_variant_and_warehouse_observations():
    base = {"candidate": candidate(), "variant": variant(), "match": SupplierMatch(outcome="MATCH")}
    with pytest.raises(ValidationError):
        SupplierOffer(**{**base, "stock": stock(variant_id="v2")})
    with pytest.raises(ValidationError):
        SupplierOffer(**{**base, "stock": stock(), "quote": quote(storage_id="s2")})


def test_quote_validates_request_quantity_expiry_delivery_and_parcel():
    for invalid in [
        {"quantity": 2},
        {"expires_at": NOW - timedelta(seconds=1)},
        {"delivery_min_days": 7, "delivery_max_days": 3},
        {"tracking": "true"},
    ]:
        with pytest.raises(ValidationError):
            quote(**invalid)
    with pytest.raises(ValidationError):
        variant(dimensions_mm=["10", "20", "-1"])
    assert variant(dimensions_mm=["10", "20", "30"]).dimensions_mm == (
        Decimal("10"),
        Decimal("20"),
        Decimal("30"),
    )


def test_confirmation_never_changes_match_and_no_match_cannot_be_selected():
    offer = SupplierOffer(
        candidate=candidate(), variant=variant(), match=SupplierMatch(outcome="LIKELY_MATCH")
    )
    selected = SupplierSelection(offer=offer, confirmed_attributes={"identity": "Lunch box"})
    assert selected.offer.match.outcome == "LIKELY_MATCH"
    with pytest.raises(ValidationError):
        SupplierSelection(
            offer=SupplierOffer(
                candidate=candidate(), variant=variant(), match=SupplierMatch(outcome="NO_MATCH")
            )
        )


def test_outcome_and_telemetry_are_safe_and_separate_partial_rejected():
    outcome = ProviderOutcome(
        status="SUCCESS", records=[variant().model_dump(mode="json")], partial=True, rejected=1
    )
    assert outcome.partial and outcome.rejected == 1
    assert (
        ProviderOutcome.model_validate_json(outcome.model_dump_json()).records[0]["id"]
        == variant().id
    )
    for invalid in [
        {"status": "SUCCESS", "records": [{"accessToken": "secret"}]},
        {"status": "SUCCESS_EMPTY", "records": [{"id": "x"}]},
        {"status": "FAILED", "rejected": -1},
    ]:
        with pytest.raises(ValidationError):
            ProviderOutcome.model_validate(invalid)
    telemetry = ActionTelemetry(requests={"auth": 1, "stock": 2})
    assert sum(telemetry.requests.values()) == 3
    with pytest.raises(ValidationError):
        ActionTelemetry(requests={"auth": -1})
    with pytest.raises(ValidationError):
        ActionTelemetry(stages=[{"headers": {"Authorization": "secret"}}])


def test_report_serializes_versioned_safe_nested_observations():
    report = SupplyIntelligenceReport(
        product_id="product1",
        input_fingerprint="fp1",
        offers=[
            SupplierOffer(
                candidate=candidate(), variant=variant(), match=SupplierMatch(outcome="MATCH")
            )
        ],
    )
    restored = SupplyIntelligenceReport.model_validate_json(report.model_dump_json())
    assert restored.schema_version == 4
    assert restored.offers[0].variant.id == variant().id
    with pytest.raises(ValidationError):
        SupplyIntelligenceReport(product_id="p1", input_fingerprint="f", schema_version=3)


@pytest.mark.parametrize(
    "dimensions", [["NaN", "20", "30"], ["bad", "20", "30"], [True, "20", "30"]]
)
def test_malformed_parcel_dimensions_are_validation_failures(dimensions):
    with pytest.raises(ValidationError):
        variant(dimensions_mm=dimensions)


def test_match_reasons_cannot_mutate_a_selected_observation_identity():
    decision = SupplierMatch(outcome="MATCH", reasons=["Comparable identity"])
    offer = SupplierOffer(candidate=candidate(), variant=variant(), match=decision)
    identity = offer.id
    with pytest.raises(TypeError):
        decision.reasons.append("Changed claim")
    assert offer.id == identity


@pytest.mark.parametrize("identity", ["p1\nheader", "p1\x00tail"])
def test_opaque_identity_rejects_control_characters(identity):
    with pytest.raises(ValidationError):
        candidate(product_id=identity)


def test_default_nested_attributes_are_also_immutable():
    with pytest.raises(TypeError):
        variant().attributes["plug"] = "US"
    with pytest.raises(TypeError):
        SupplierMatch(outcome="MATCH").reasons.append("Changed fact")


def test_generic_token_field_is_not_a_safe_record():
    with pytest.raises(ValidationError):
        ProviderOutcome(status="SUCCESS", records=[{"token": "secret"}])
