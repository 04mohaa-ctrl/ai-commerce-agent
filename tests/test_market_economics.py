"""V3 financial assumptions stay explicit and preserve V2 calculations."""

import math

import pytest
from pydantic import ValidationError

LANDED_FIELDS = (
    "unit_product_cost",
    "international_shipping_per_unit",
    "import_duty_per_unit",
    "customs_fee_per_unit",
    "packaging_per_unit",
    "handling_per_unit",
    "other_variable_cost_per_unit",
)
MONEY_FIELDS = LANDED_FIELDS + (
    "payment_fixed_fee",
    "estimated_loss_per_return",
    "estimated_ad_cost_per_order",
)
COMPLETE_EXAMPLE = {
    "unit_product_cost": 10,
    "international_shipping_per_unit": 5,
    "import_duty_per_unit": 0,
    "customs_fee_per_unit": 0,
    "packaging_per_unit": 0,
    "handling_per_unit": 0,
    "other_variable_cost_per_unit": 0,
    "selling_price": 40,
    "payment_fee_percent": 3,
    "payment_fixed_fee": 0.30,
    "return_rate_percent": 8,
    "estimated_loss_per_return": 12,
    "estimated_ad_cost_per_order": 8,
}


def test_landed_cost_sums_all_seven_explicit_components():
    from src.services.landed_cost import LandedCostInputs, calculate_landed_cost

    result = calculate_landed_cost(LandedCostInputs(**dict(zip(LANDED_FIELDS, range(1, 8)))))
    assert result == 28.0
    assert isinstance(result, float)


@pytest.mark.parametrize("field", LANDED_FIELDS)
def test_each_missing_landed_component_keeps_total_unknown(field):
    from src.services.landed_cost import LandedCostInputs, calculate_landed_cost

    values = dict.fromkeys(LANDED_FIELDS, 0)
    values[field] = None
    assert calculate_landed_cost(LandedCostInputs(**values)) is None


def test_explicit_zero_landed_cost_is_known():
    from src.services.landed_cost import LandedCostInputs, calculate_landed_cost

    assert calculate_landed_cost(LandedCostInputs()) is None
    assert calculate_landed_cost(LandedCostInputs(**dict.fromkeys(LANDED_FIELDS, 0))) == 0.0


def test_complete_v3_example_has_fixed_fees_and_expected_return_loss():
    from src.services.market_economics import MarketEconomicsInputs, calculate_market_economics

    result = calculate_market_economics(MarketEconomicsInputs(**COMPLETE_EXAMPLE))
    assert result.revenue_per_order == 40.0
    assert result.landed_cost == 15.0
    assert result.gross_profit_before_marketing == 25.0
    assert result.payment_cost == 1.50
    assert result.expected_return_cost == 0.96
    assert result.contribution_before_ads == 22.54
    assert result.estimated_ad_cost == 8.0
    assert result.estimated_net_profit == 14.54
    assert result.estimated_net_margin_percent == 36.35
    assert result.break_even_ad_cost == 22.54
    assert result.missing_inputs == []
    assert result.complete is True


def test_empty_inputs_leave_all_outputs_unknown_and_identify_missing_assumptions():
    from src.services.market_economics import MarketEconomicsInputs, calculate_market_economics

    result = calculate_market_economics(MarketEconomicsInputs())
    for field in (
        "revenue_per_order",
        "landed_cost",
        "gross_profit_before_marketing",
        "payment_cost",
        "expected_return_cost",
        "contribution_before_ads",
        "estimated_ad_cost",
        "estimated_net_profit",
        "estimated_net_margin_percent",
        "break_even_ad_cost",
    ):
        assert getattr(result, field) is None
    assert set(result.missing_inputs) == set(COMPLETE_EXAMPLE)
    assert result.complete is False


@pytest.mark.parametrize("field", tuple(COMPLETE_EXAMPLE))
def test_missing_assumption_blocks_only_dependent_outputs(field):
    from src.services.market_economics import MarketEconomicsInputs, calculate_market_economics

    values = COMPLETE_EXAMPLE | {field: None}
    result = calculate_market_economics(MarketEconomicsInputs(**values))
    assert result.missing_inputs == [field]
    assert result.complete is False
    assert result.revenue_per_order == (None if field == "selling_price" else 40.0)
    assert result.landed_cost == (None if field in LANDED_FIELDS else 15.0)
    assert result.gross_profit_before_marketing == (
        None if field in LANDED_FIELDS + ("selling_price",) else 25.0
    )
    assert result.payment_cost == (
        None if field in ("selling_price", "payment_fee_percent", "payment_fixed_fee") else 1.50
    )
    assert result.expected_return_cost == (
        None if field in ("return_rate_percent", "estimated_loss_per_return") else 0.96
    )
    assert result.estimated_ad_cost == (None if field == "estimated_ad_cost_per_order" else 8.0)
    assert result.contribution_before_ads == (
        22.54 if field == "estimated_ad_cost_per_order" else None
    )
    assert result.break_even_ad_cost == (22.54 if field == "estimated_ad_cost_per_order" else None)
    assert result.estimated_net_profit is None
    assert result.estimated_net_margin_percent is None


def test_zero_return_rate_does_not_supply_missing_loss_assumption():
    from src.services.market_economics import MarketEconomicsInputs, calculate_market_economics

    result = calculate_market_economics(
        MarketEconomicsInputs(
            **(
                COMPLETE_EXAMPLE
                | {
                    "return_rate_percent": 0,
                    "estimated_loss_per_return": None,
                }
            )
        )
    )
    assert result.expected_return_cost is None
    assert result.contribution_before_ads is None
    assert result.estimated_net_profit is None


def test_zero_percent_fee_does_not_supply_missing_fixed_fee():
    from src.services.market_economics import MarketEconomicsInputs, calculate_market_economics

    result = calculate_market_economics(
        MarketEconomicsInputs(
            **(
                COMPLETE_EXAMPLE
                | {
                    "payment_fee_percent": 0,
                    "payment_fixed_fee": None,
                }
            )
        )
    )
    assert result.payment_cost is None
    assert result.estimated_net_profit is None


def test_negative_contribution_and_profit_are_preserved():
    from src.services.market_economics import MarketEconomicsInputs, calculate_market_economics

    result = calculate_market_economics(
        MarketEconomicsInputs(**(COMPLETE_EXAMPLE | {"selling_price": 10}))
    )
    assert result.gross_profit_before_marketing == -5.0
    assert result.contribution_before_ads == -6.56
    assert result.break_even_ad_cost == -6.56
    assert result.estimated_net_profit == -14.56
    assert result.estimated_net_margin_percent == -145.6


@pytest.mark.parametrize(
    "price,fee,fixed,rate,loss,payment,returns,net,margin",
    [
        (10.5, 1, 0, 1, 10.5, 0.11, 0.11, 10.28, 97.90),
        (1, 1.5, 0.01, 0.5, 1, 0.03, 0.01, 0.96, 96.0),
        (40, 0, 0.30, 100, 12, 0.30, 12.0, 27.70, 69.25),
    ],
)
def test_fee_and_return_rounding_is_half_up_at_currency_boundary(
    price, fee, fixed, rate, loss, payment, returns, net, margin
):
    from src.services.market_economics import MarketEconomicsInputs, calculate_market_economics

    result = calculate_market_economics(
        MarketEconomicsInputs(
            **dict.fromkeys(LANDED_FIELDS, 0),
            selling_price=price,
            payment_fee_percent=fee,
            payment_fixed_fee=fixed,
            return_rate_percent=rate,
            estimated_loss_per_return=loss,
            estimated_ad_cost_per_order=0,
        )
    )
    assert result.payment_cost == payment
    assert result.expected_return_cost == returns
    assert result.estimated_net_profit == net
    assert result.estimated_net_margin_percent == margin


def test_money_inputs_are_half_up_cents_before_calculation():
    from src.services.market_economics import MarketEconomicsInputs, calculate_market_economics

    values = dict.fromkeys(LANDED_FIELDS, 0.005) | {
        "selling_price": 40.005,
        "payment_fee_percent": 0,
        "payment_fixed_fee": 0.005,
        "return_rate_percent": 100,
        "estimated_loss_per_return": 0.005,
        "estimated_ad_cost_per_order": 0.005,
    }
    result = calculate_market_economics(MarketEconomicsInputs(**values))
    assert result.revenue_per_order == 40.01
    assert result.landed_cost == 0.07
    assert result.payment_cost == 0.01
    assert result.expected_return_cost == 0.01
    assert result.estimated_ad_cost == 0.01
    assert result.estimated_net_profit == 39.91


@pytest.mark.parametrize("field", MONEY_FIELDS)
@pytest.mark.parametrize("value", [-0.01, 1_000_000.01, math.nan, math.inf, -math.inf])
def test_invalid_cost_assumptions_are_rejected(field, value):
    from src.services.market_economics import MarketEconomicsInputs

    with pytest.raises(ValidationError):
        MarketEconomicsInputs(**{field: value})


@pytest.mark.parametrize("field", ["payment_fee_percent", "return_rate_percent"])
@pytest.mark.parametrize("value", [-0.01, 100.01, math.nan, math.inf, -math.inf])
def test_invalid_percent_assumptions_are_rejected(field, value):
    from src.services.market_economics import MarketEconomicsInputs

    with pytest.raises(ValidationError):
        MarketEconomicsInputs(**{field: value})


@pytest.mark.parametrize("value", [0, -0.01, 0.001, 1_000_000.01, math.nan, math.inf])
def test_invalid_selling_price_is_rejected(value):
    from src.services.market_economics import MarketEconomicsInputs

    with pytest.raises(ValidationError):
        MarketEconomicsInputs(selling_price=value)


def test_maximum_allowed_costs_do_not_clamp_total_or_negative_profit():
    from src.services.market_economics import MarketEconomicsInputs, calculate_market_economics

    result = calculate_market_economics(
        MarketEconomicsInputs(
            **dict.fromkeys(LANDED_FIELDS, 1_000_000),
            selling_price=0.01,
            payment_fee_percent=100,
            payment_fixed_fee=1_000_000,
            return_rate_percent=100,
            estimated_loss_per_return=1_000_000,
            estimated_ad_cost_per_order=1_000_000,
        )
    )
    assert result.landed_cost == 7_000_000.0
    assert result.break_even_ad_cost == -9_000_000.0
    assert result.estimated_net_profit == -10_000_000.0
    assert result.complete is True


def test_v3_inputs_do_not_accept_legacy_ambiguous_shipping():
    from src.services.market_economics import MarketEconomicsInputs

    with pytest.raises(ValidationError):
        MarketEconomicsInputs(shipping_cost=5)


def test_original_v2_example_keeps_its_original_result():
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
    assert result.estimated_net_profit == 15.80
    assert result.estimated_net_margin_percent == 39.50
    assert result.break_even_ad_cost == 23.80
