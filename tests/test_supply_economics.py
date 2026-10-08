from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.services.market_economics import MarketEconomicsInputs
from src.supply.economics import (
    FinancialSnapshot,
    apply_shipping_cost,
    apply_supplier_cost,
    calculate_financial,
    save_manual_inputs,
)

NOW = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)


def selection():
    from src.supply.models import (
        Destination,
        ShippingQuote,
        StockObservation,
        SupplierMatch,
        SupplierOffer,
        SupplierProductCandidate,
        SupplierSelection,
        SupplierVariant,
    )

    candidate = SupplierProductCandidate(
        provider="cj",
        product_id="p1",
        name="Lunch box",
        source_url="https://cjdropshipping.com/product/p1.html",
        observed_at=NOW,
    )
    variant = SupplierVariant(
        provider="cj",
        product_id="p1",
        variant_id="v1",
        name="Lunch box",
        attributes={"voltage": "120V", "plug": "US"},
        unit_price=Decimal("10"),
        currency="USD",
        observed_at=NOW,
    )
    stock = StockObservation(
        provider="cj",
        product_id="p1",
        variant_id="v1",
        warehouse_id="w1",
        storage_id="s1",
        country="CN",
        quantity=20,
        observed_at=NOW,
    )
    quote = ShippingQuote(
        provider="cj",
        product_id="p1",
        variant_id="v1",
        variant_snapshot=variant.id,
        warehouse_id="w1",
        storage_id="s1",
        origin="CN",
        destination=Destination(quantity=2),
        quantity=2,
        method="standard",
        total_cost=Decimal("10"),
        currency="USD",
        delivery_max_days=10,
        observed_at=NOW,
    )
    return SupplierSelection(
        offer=SupplierOffer(
            candidate=candidate,
            variant=variant,
            stock=stock,
            quote=quote,
            match=SupplierMatch(outcome="MATCH"),
        ),
        selected_at=NOW,
    )


def complete_inputs(**changes):
    values = dict(
        unit_product_cost=10,
        international_shipping_per_unit=5,
        import_duty_per_unit=0,
        customs_fee_per_unit=0,
        packaging_per_unit=0,
        handling_per_unit=0,
        other_variable_cost_per_unit=0,
        selling_price=40,
        payment_fee_percent=3,
        payment_fixed_fee=0.30,
        return_rate_percent=8,
        estimated_loss_per_return=12,
        estimated_ad_cost_per_order=8,
    )
    values.update(changes)
    return MarketEconomicsInputs(**values)


def updated_selection(chosen, part, **changes):
    record = getattr(chosen.offer, part).model_copy(update=changes)
    offer = chosen.offer.model_copy(update={part: record})
    return chosen.model_copy(update={"offer": offer})


def test_failed_selected_storage_is_not_masked_by_another_subwarehouse_success():
    from src.supply.economics import shipping_issue
    from src.supply.models import Destination

    stages = [
        {
            "component": "shipping",
            "provider": "cj",
            "warehouse_id": "w1",
            "storage_id": "s1",
            "status": "FAILED",
        },
        {
            "component": "shipping",
            "provider": "cj",
            "warehouse_id": "w1",
            "storage_id": "s2",
            "status": "SUCCESS",
        },
    ]
    assert shipping_issue(selection(), Destination(quantity=2), "USD", NOW, stages) is not None


def test_shipping_quote_cannot_survive_changed_parcel_observation():
    from src.supply.economics import shipping_issue
    from src.supply.models import Destination

    chosen = updated_selection(selection(), "variant", weight_g=2000)
    assert shipping_issue(chosen, Destination(quantity=2), "USD", NOW) is not None


def test_monetary_input_cannot_bypass_currency_guard_with_percent_unit():
    from pydantic import ValidationError

    from src.supply.economics import FinancialInputProvenance

    snapshot = FinancialSnapshot(inputs=complete_inputs())
    provenance = dict(snapshot.provenance)
    provenance["unit_product_cost"] = FinancialInputProvenance(
        value=10, currency="EUR", unit="percent", source_kind="ESTIMATED"
    )
    with pytest.raises(ValidationError):
        FinancialSnapshot(inputs=complete_inputs(), provenance=provenance)


def test_initial_manual_copy_tracks_every_field_unknown_and_explicit_zero():
    inputs = MarketEconomicsInputs(selling_price=40, packaging_per_unit=0)
    snapshot = FinancialSnapshot(inputs=inputs, updated_at=NOW)
    inputs.selling_price = 99
    assert snapshot.inputs.selling_price == 40
    assert set(snapshot.provenance) == set(MarketEconomicsInputs.model_fields)
    assert snapshot.provenance["packaging_per_unit"].source_kind == "ESTIMATED"
    assert snapshot.provenance["customs_fee_per_unit"].source_kind == "UNKNOWN"
    assert snapshot.provenance["customs_fee_per_unit"].value is None


def test_explicit_cost_application_copies_revision_and_keeps_unknown_costs():
    from src.supply.models import Destination

    original = FinancialSnapshot(inputs=MarketEconomicsInputs(selling_price=40), updated_at=NOW)
    chosen = selection()
    cost = apply_supplier_cost(original, chosen, Destination(quantity=2), NOW)
    final = apply_shipping_cost(cost, chosen, Destination(quantity=2), NOW)
    assert original.inputs.unit_product_cost is None
    assert final.revision == original.revision + 2
    assert (
        final.inputs.unit_product_cost == 10 and final.inputs.international_shipping_per_unit == 5
    )
    assert final.inputs.import_duty_per_unit is None
    assert final.provenance["unit_product_cost"].observation_id == chosen.offer.variant.id
    freight = final.provenance["international_shipping_per_unit"]
    assert freight.observation_id == chosen.offer.quote.id and "2" in freight.derivation
    assert freight.value == Decimal("5")


@pytest.mark.parametrize(
    "bad", ["ambiguous", "unconfirmed", "fabricated_confirmation", "stale_cost", "currency"]
)
def test_ineligible_supplier_cost_is_rejected_without_mutation(bad):
    from src.supply.models import Destination

    chosen = selection()
    if bad == "ambiguous":
        chosen = updated_selection(chosen, "match", outcome="AMBIGUOUS")
    if bad in {"unconfirmed", "fabricated_confirmation"}:
        chosen = updated_selection(chosen, "match", outcome="LIKELY_MATCH")
    if bad == "fabricated_confirmation":
        chosen = chosen.model_copy(
            update={"confirmed_attributes": {"voltage": "240V", "plug": "EU"}}
        )
    if bad == "stale_cost":
        chosen = updated_selection(chosen, "variant", observed_at=NOW - timedelta(days=2))
    if bad == "currency":
        chosen = updated_selection(chosen, "variant", currency="EUR")
    snapshot = FinancialSnapshot(inputs=complete_inputs(), updated_at=NOW)
    before = snapshot.model_dump_json()
    with pytest.raises(ValueError):
        apply_supplier_cost(snapshot, chosen, Destination(quantity=2), NOW)
    assert snapshot.model_dump_json() == before


def test_likely_match_requires_actual_attribute_confirmation():
    from src.supply.models import Destination

    chosen = selection()
    chosen = updated_selection(chosen, "match", outcome="LIKELY_MATCH")
    chosen = chosen.model_copy(
        update={"confirmed_attributes": dict(chosen.offer.variant.attributes)}
    )
    snapshot = FinancialSnapshot(inputs=MarketEconomicsInputs(), updated_at=NOW)
    assert (
        apply_supplier_cost(snapshot, chosen, Destination(quantity=2), NOW).inputs.unit_product_cost
        == 10
    )


@pytest.mark.parametrize(
    "bad",
    [
        "country",
        "quantity",
        "warehouse",
        "storage",
        "variant",
        "origin",
        "expired",
        "stale",
        "currency",
        "stock_unknown",
    ],
)
def test_shipping_requires_exact_fresh_compatible_binding(bad):
    from src.supply.models import Destination

    chosen = selection()
    snapshot = FinancialSnapshot(inputs=complete_inputs(), updated_at=NOW)
    changes = {
        "country": {"destination": Destination(country="SE", quantity=2)},
        "quantity": {"quantity": 3, "destination": Destination(quantity=3)},
        "warehouse": {"warehouse_id": "other"},
        "storage": {"storage_id": "other"},
        "variant": {"variant_id": "other"},
        "origin": {"origin": "US"},
        "expired": {
            "observed_at": NOW - timedelta(hours=2),
            "expires_at": NOW - timedelta(seconds=1),
        },
        "stale": {"observed_at": NOW - timedelta(hours=7)},
        "currency": {"currency": "EUR"},
    }
    with pytest.raises(ValueError):
        # Strict snapshot contracts reject mismatched variant/warehouse identities first.
        if bad == "stock_unknown":
            stock = chosen.offer.stock.model_copy(update={"storage_id": None})
            quote = chosen.offer.quote.model_copy(update={"storage_id": None})
            chosen = chosen.model_copy(
                update={"offer": chosen.offer.model_copy(update={"stock": stock, "quote": quote})}
            )
        else:
            chosen = updated_selection(chosen, "quote", **changes[bad])
        apply_shipping_cost(snapshot, chosen, Destination(quantity=2), NOW)


def test_manual_edits_preserve_unchanged_observed_provenance_and_refresh_never_aliases():
    from src.supply.models import Destination

    chosen = selection()
    snapshot = apply_supplier_cost(
        FinancialSnapshot(inputs=complete_inputs(), updated_at=NOW),
        chosen,
        Destination(quantity=2),
        NOW,
    )
    updated = save_manual_inputs(snapshot, complete_inputs(estimated_ad_cost_per_order=9))
    refreshed = updated_selection(chosen, "variant", unit_price=Decimal("99"))
    assert refreshed.offer.variant.unit_price == 99
    assert updated.inputs.unit_product_cost == 10
    assert updated.provenance["unit_product_cost"].source_kind == "OBSERVED"
    assert updated.provenance["estimated_ad_cost_per_order"].source_kind == "ESTIMATED"
    assert updated.revision == snapshot.revision + 1


def test_financial_derived_revision_and_v3_pinned_values_stay_unchanged():
    from src.supply.financial_scenario import TaxAssumptions

    snapshot = FinancialSnapshot(
        inputs=complete_inputs(),
        updated_at=NOW,
        tax_assumptions=TaxAssumptions(price_basis="NO_VAT", import_vat_per_unit=0),
    )
    result = calculate_financial(snapshot, now=NOW)
    assert result.revision == snapshot.revision
    assert result.economics.estimated_net_profit == 14.54
    assert result.economics.break_even_ad_cost == 22.54
    assert result.known_cost_subtotal == Decimal("15")


def test_stale_or_cross_currency_provenance_blocks_current_total_preserves_history():
    from src.supply.models import Destination

    chosen = selection()
    snapshot = apply_supplier_cost(
        FinancialSnapshot(inputs=complete_inputs(), updated_at=NOW),
        chosen,
        Destination(quantity=2),
        NOW,
    )
    stale = calculate_financial(
        snapshot, selection=chosen, destination=Destination(quantity=2), now=NOW + timedelta(days=2)
    )
    assert not stale.current and stale.economics is None
    assert snapshot.inputs.unit_product_cost == 10
    snapshot.provenance["unit_product_cost"].currency = "EUR"
    invalid = calculate_financial(snapshot, now=NOW)
    assert not invalid.compatible and invalid.economics is None


def test_changed_destination_rechecks_selected_electrical_compatibility():
    from src.supply.models import Destination

    chosen = selection()
    snapshot = FinancialSnapshot(inputs=complete_inputs(), updated_at=NOW)
    with pytest.raises(ValueError, match="destination|Destination"):
        apply_supplier_cost(snapshot, chosen, Destination(country="SE", quantity=2), NOW)
