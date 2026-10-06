import math

import pytest
from pydantic import ValidationError


def test_known_profit_and_break_even_example():
    from src.services.economics import EconomicsInputs, calculate_economics

    result = calculate_economics(
        EconomicsInputs(
            product_cost=10,
            selling_price=40,
            shipping_cost=5,
            payment_fee_percent=3,
            estimated_ad_cost_per_order=8,
        )
    )
    assert result.gross_profit == 25
    assert result.gross_margin_percent == 62.5
    assert result.payment_fee == 1.2
    assert result.estimated_net_profit == 15.8
    assert result.estimated_net_margin_percent == 39.5
    assert result.break_even_ad_cost == 23.8
    assert result.complete is True


def test_unknown_costs_do_not_silently_become_zero():
    from src.services.economics import EconomicsInputs, calculate_economics

    unknown = calculate_economics(EconomicsInputs(product_cost=10, selling_price=40))
    assert unknown.gross_profit is None
    assert unknown.estimated_net_profit is None
    assert unknown.break_even_ad_cost is None
    assert set(unknown.missing_inputs) == {
        "shipping_cost",
        "payment_fee_percent",
        "estimated_ad_cost_per_order",
    }
    no_ads = calculate_economics(
        EconomicsInputs(product_cost=10, selling_price=40, shipping_cost=5, payment_fee_percent=3)
    )
    assert no_ads.break_even_ad_cost == 23.8
    assert no_ads.estimated_net_profit is None


def test_negative_break_even_means_no_profitable_cpa():
    from src.services.economics import EconomicsInputs, calculate_economics

    loss = calculate_economics(
        EconomicsInputs(
            product_cost=20,
            selling_price=10,
            shipping_cost=2,
            payment_fee_percent=3,
            estimated_ad_cost_per_order=0,
        )
    )
    assert loss.break_even_ad_cost == -12.3
    assert loss.estimated_net_profit == -12.3
    assert loss.estimated_net_margin_percent == -123


def test_decimal_rounding_is_consistent_for_money():
    from src.services.economics import EconomicsInputs, calculate_economics

    result = calculate_economics(
        EconomicsInputs(
            product_cost=0,
            selling_price=10.5,
            shipping_cost=0,
            payment_fee_percent=1,
            estimated_ad_cost_per_order=0,
        )
    )
    assert result.payment_fee == 0.11
    assert result.estimated_net_profit == 10.39


@pytest.mark.parametrize(
    "field,value",
    [
        ("product_cost", -1),
        ("selling_price", 0),
        ("shipping_cost", -1),
        ("payment_fee_percent", 101),
        ("estimated_ad_cost_per_order", -1),
        ("selling_price", math.nan),
        ("shipping_cost", math.inf),
    ],
)
def test_invalid_economic_assumptions_are_rejected(field, value):
    from src.services.economics import EconomicsInputs

    with pytest.raises(ValidationError):
        EconomicsInputs(**({"product_cost": 10, "selling_price": 40} | {field: value}))
