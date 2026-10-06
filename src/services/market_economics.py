"""V3 unit economics with explicit landed, payment, return and advertising costs."""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator

from src.services.economics import Cost, FeePercent, Price, cents
from src.services.landed_cost import LandedCostInputs, calculate_landed_cost


class MarketEconomicsInputs(LandedCostInputs):
    selling_price: Price | None = None
    payment_fee_percent: FeePercent | None = None
    payment_fixed_fee: Cost | None = None
    return_rate_percent: FeePercent | None = None
    estimated_loss_per_return: Cost | None = None
    estimated_ad_cost_per_order: Cost | None = None

    @field_validator(
        "selling_price",
        "payment_fixed_fee",
        "estimated_loss_per_return",
        "estimated_ad_cost_per_order",
    )
    @classmethod
    def round_market_currency(cls, value: float | None) -> float | None:
        return float(cents(Decimal(str(value)))) if value is not None else None


class MarketEconomicsResult(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    revenue_per_order: float | None
    landed_cost: float | None
    gross_profit_before_marketing: float | None
    payment_cost: float | None
    expected_return_cost: float | None
    contribution_before_ads: float | None
    estimated_ad_cost: float | None
    estimated_net_profit: float | None
    estimated_net_margin_percent: float | None
    break_even_ad_cost: float | None
    missing_inputs: list[str]

    @property
    def complete(self) -> bool:
        return not self.missing_inputs


def calculate_market_economics(inputs: MarketEconomicsInputs) -> MarketEconomicsResult:
    """Calculate each output only from known dependencies, using Decimal arithmetic."""

    def decimal(value: float | None) -> Decimal | None:
        return Decimal(str(value)) if value is not None else None

    def money(value: Decimal | None) -> float | None:
        return float(cents(value)) if value is not None else None

    price = decimal(inputs.selling_price)
    landed = decimal(calculate_landed_cost(inputs))
    ad_cost = decimal(inputs.estimated_ad_cost_per_order)
    fee_percent = decimal(inputs.payment_fee_percent)
    fixed_fee = decimal(inputs.payment_fixed_fee)
    return_rate = decimal(inputs.return_rate_percent)
    return_loss = decimal(inputs.estimated_loss_per_return)

    gross = price - landed if price is not None and landed is not None else None
    payment = (
        cents(price * fee_percent / 100 + fixed_fee)
        if price is not None and fee_percent is not None and fixed_fee is not None
        else None
    )
    returns = (
        cents(return_rate / 100 * return_loss)
        if return_rate is not None and return_loss is not None
        else None
    )
    contribution = (
        gross - payment - returns
        if gross is not None and payment is not None and returns is not None
        else None
    )
    net = contribution - ad_cost if contribution is not None and ad_cost is not None else None
    margin = net / price * 100 if net is not None and price is not None else None

    return MarketEconomicsResult(
        revenue_per_order=money(price),
        landed_cost=money(landed),
        gross_profit_before_marketing=money(gross),
        payment_cost=money(payment),
        expected_return_cost=money(returns),
        contribution_before_ads=money(contribution),
        estimated_ad_cost=money(ad_cost),
        estimated_net_profit=money(net),
        estimated_net_margin_percent=money(margin),
        break_even_ad_cost=money(contribution),
        missing_inputs=[
            field for field in MarketEconomicsInputs.model_fields if getattr(inputs, field) is None
        ],
    )
