"""Hand-derived V4 scenarios; these are assumptions, never live tax determinations."""

from datetime import date

import pytest

from src.services.market_economics import calculate_market_economics
from src.supply.economics import FinancialSnapshot, calculate_financial
from tests.test_supply_economics import NOW, complete_inputs


def test_legacy_snapshot_does_not_silently_declare_tax_treatment():
    snapshot = FinancialSnapshot(inputs=complete_inputs(), updated_at=NOW)
    result = calculate_financial(snapshot, now=NOW)
    assert result.economics.estimated_net_profit is None
    assert "price_basis" in result.missing_inputs
    # V3's pinned arithmetic and saved inputs remain unchanged.
    assert calculate_market_economics(snapshot.inputs).estimated_net_profit == 14.54
    assert snapshot.inputs.selling_price == 40


@pytest.mark.parametrize(
    "basis,price,quantity,revenue,payment,landed,profit,cpa",
    [
        ("VAT_INCLUSIVE", 50, 1, 40, 1.8, 17, 12.24, 20.24),
        ("VAT_EXCLUSIVE", 40, 1, 40, 1.8, 17, 12.24, 20.24),
        ("VAT_INCLUSIVE", 50, 2, 80, 3.3, 17, 33.74, 41.74),
    ],
)
def test_vat_revenue_customer_payment_fees_and_order_quantity(
    basis, price, quantity, revenue, payment, landed, profit, cpa
):
    from src.supply.financial_scenario import TaxAssumptions, calculate_v4_economics

    tax = TaxAssumptions(
        price_basis=basis,
        sales_vat_percent=25,
        import_vat_per_unit=4,
        import_vat_recoverable_percent=50,
    )
    result = calculate_v4_economics(complete_inputs(selling_price=price), tax, quantity)
    assert result.revenue_per_order == revenue
    assert result.payment_cost == payment
    assert result.landed_cost == landed
    assert result.estimated_net_profit == profit
    assert result.break_even_ad_cost == cpa
    assert result.complete


@pytest.mark.parametrize("recoverable,landed", [(0, 19), (50, 17), (100, 15)])
def test_import_vat_only_unrecoverable_amount_is_a_cost(recoverable, landed):
    from src.supply.financial_scenario import TaxAssumptions, calculate_v4_economics

    tax = TaxAssumptions(
        price_basis="NO_VAT", import_vat_per_unit=4, import_vat_recoverable_percent=recoverable
    )
    assert calculate_v4_economics(complete_inputs(), tax).landed_cost == landed


def test_missing_tax_does_not_become_zero_and_dependencies_are_independent():
    from src.supply.financial_scenario import TaxAssumptions, calculate_v4_economics

    result = calculate_v4_economics(complete_inputs(), TaxAssumptions())
    assert result.landed_cost is None and result.revenue_per_order is None
    assert result.break_even_ad_cost is None and not result.complete
    explicit = calculate_v4_economics(
        complete_inputs(estimated_ad_cost_per_order=None),
        TaxAssumptions(price_basis="NO_VAT", import_vat_per_unit=0),
    )
    assert explicit.landed_cost == 15
    assert explicit.break_even_ad_cost == 22.54
    assert explicit.estimated_net_profit is None


def test_price_conversion_records_rate_date_source_and_survives_adoption(tmp_path):
    from src.database.database import ProductRepository
    from src.database.supply_repository import SupplyRepository
    from src.supply.economics import save_customer_price, save_manual_inputs, save_tax_assumptions
    from src.supply.financial_scenario import PriceConversion, TaxAssumptions

    original = FinancialSnapshot(inputs=complete_inputs(), updated_at=NOW)
    conversion = PriceConversion(
        customer_price=349,
        currency="SEK",
        usd_per_currency=0.1,
        rate_date=date(2026, 10, 8),
        source="Explicit test estimate",
    )
    converted = save_customer_price(original, conversion)
    assert converted.inputs.selling_price == 34.9
    assert converted.price_conversion.source == "Explicit test estimate"
    assert "SEK" in converted.provenance["selling_price"].derivation
    updated = save_tax_assumptions(
        converted, TaxAssumptions(price_basis="NO_VAT", import_vat_per_unit=0)
    )
    updated = save_manual_inputs(
        updated, updated.inputs.model_copy(update={"handling_per_unit": 1})
    )
    ext = SupplyRepository(ProductRepository(tmp_path / "scenario.db"))
    ext.save_financial("product", updated)
    reopened = SupplyRepository(ProductRepository(tmp_path / "scenario.db")).get_financial(
        "product"
    )
    assert reopened.tax_assumptions.price_basis == "NO_VAT"
    assert reopened.price_conversion.rate_date == date(2026, 10, 8)
    assert reopened.provenance["handling_per_unit"].source_kind == "ESTIMATED"
    changed = save_manual_inputs(reopened, reopened.inputs.model_copy(update={"selling_price": 35}))
    assert changed.price_conversion is None  # Old FX must not describe a new manual price.


def test_legacy_json_roundtrip_does_not_rewrite_original_records(tmp_path):
    from src.database.database import ProductRepository
    from src.database.supply_repository import SupplyRepository

    ext = SupplyRepository(ProductRepository(tmp_path / "old.db"))
    old = FinancialSnapshot(inputs=complete_inputs(), updated_at=NOW).model_dump(mode="json")
    old.pop("tax_assumptions", None)
    old.pop("price_conversion", None)
    ext._save("financial", "old", "old", old)
    reopened = ext.get_financial("old")
    assert reopened.inputs.selling_price == 40
    assert calculate_financial(reopened, now=NOW).economics.estimated_net_profit is None
    assert ext._get("financial", "old") == old


def test_fx_requires_usd_snapshot_and_a_known_agreeing_price():
    from pydantic import ValidationError

    from src.supply.financial_scenario import PriceConversion

    fx = PriceConversion(
        customer_price=100,
        currency="SEK",
        usd_per_currency=0.1,
        rate_date=date(2026, 10, 8),
        source="Test estimate",
    )
    for currency, price in [("EUR", 10), ("USD", None), ("USD", 11)]:
        with pytest.raises(ValidationError):
            FinancialSnapshot(
                inputs=complete_inputs(selling_price=price), currency=currency, price_conversion=fx
            )


def test_financial_revision_owns_tax_assumptions():
    from src.supply.financial_scenario import TaxAssumptions

    tax = TaxAssumptions(price_basis="NO_VAT", import_vat_per_unit=0)
    snapshot = FinancialSnapshot(inputs=complete_inputs(), tax_assumptions=tax)
    tax.import_vat_per_unit = 100
    assert snapshot.tax_assumptions.import_vat_per_unit == 0


@pytest.mark.parametrize("quantity", [3, 1000])
def test_adopted_freight_preserves_exact_order_total_across_unit_rounding(quantity):
    from src.supply.economics import apply_shipping_cost
    from src.supply.financial_scenario import TaxAssumptions
    from src.supply.models import Destination
    from tests.test_supply_economics import selection, updated_selection

    dest = Destination(quantity=quantity)
    chosen = updated_selection(
        selection(), "quote", quantity=quantity, destination=dest, total_cost="14.99"
    )
    snapshot = FinancialSnapshot(
        inputs=complete_inputs(
            payment_fee_percent=0,
            payment_fixed_fee=0,
            return_rate_percent=0,
            estimated_loss_per_return=0,
            estimated_ad_cost_per_order=0,
        ),
        tax_assumptions=TaxAssumptions(price_basis="NO_VAT", import_vat_per_unit=0),
        updated_at=NOW,
    )
    adopted = apply_shipping_cost(snapshot, chosen, dest, NOW)
    result = calculate_financial(adopted, chosen, dest, now=NOW)
    expected = quantity * (40 - 10) - 14.99
    assert result.economics.estimated_net_profit == expected
    assert result.economics.break_even_ad_cost == expected
    assert result.landed_cost_per_order == quantity * 10 + 14.99


def test_selling_price_provenance_is_per_unit_with_read_only_legacy_migration(tmp_path):
    from src.database.database import ProductRepository
    from src.database.supply_repository import SupplyRepository

    snapshot = FinancialSnapshot(inputs=complete_inputs(), updated_at=NOW)
    assert snapshot.provenance["selling_price"].unit == "per_unit"
    old = snapshot.model_dump(mode="json")
    old["provenance"]["selling_price"]["unit"] = "per_order"
    old.pop("tax_assumptions")
    old.pop("price_conversion")
    ext = SupplyRepository(ProductRepository(tmp_path / "legacy-price.db"))
    ext._save("financial", "old", "old", old)
    reopened = ext.get_financial("old")
    assert reopened.provenance["selling_price"].unit == "per_unit"
    assert "legacy" in reopened.provenance["selling_price"].derivation.lower()
    assert ext._get("financial", "old") == old
