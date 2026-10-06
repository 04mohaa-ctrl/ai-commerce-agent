"""Deterministic USD unit economics; unknown inputs never become zero costs."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

Cost = Annotated[float, Field(ge=0, le=1_000_000)]
Price = Annotated[float, Field(ge=0.01, le=1_000_000)]
FeePercent = Annotated[float, Field(ge=0, le=100)]


def cents(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class EconomicsInputs(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    product_cost: Cost | None = None
    selling_price: Price | None = None
    shipping_cost: Cost | None = None
    payment_fee_percent: FeePercent | None = None
    estimated_ad_cost_per_order: Cost | None = None

    @field_validator(
        "product_cost", "selling_price", "shipping_cost", "estimated_ad_cost_per_order"
    )
    @classmethod
    def round_currency(cls, value: float | None) -> float | None:
        return float(cents(Decimal(str(value)))) if value is not None else None


class EconomicsResult(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    gross_profit: float | None
    gross_margin_percent: float | None
    payment_fee: float | None
    estimated_net_profit: float | None
    estimated_net_margin_percent: float | None
    break_even_ad_cost: float | None
    missing_inputs: list[str]

    @property
    def complete(self) -> bool:
        return not self.missing_inputs


def calculate_economics(inputs: EconomicsInputs) -> EconomicsResult:
    """After-shipping gross profit and estimated net profit, excluding tax/returns/overhead."""
    price = Decimal(str(inputs.selling_price)) if inputs.selling_price is not None else None
    gross = None
    fee = None
    break_even = None
    net = None
    if price is not None and inputs.product_cost is not None and inputs.shipping_cost is not None:
        gross = price - Decimal(str(inputs.product_cost)) - Decimal(str(inputs.shipping_cost))
    if price is not None and inputs.payment_fee_percent is not None:
        fee = cents(price * Decimal(str(inputs.payment_fee_percent)) / 100)
    if gross is not None and fee is not None:
        break_even = gross - fee
        if inputs.estimated_ad_cost_per_order is not None:
            net = break_even - Decimal(str(inputs.estimated_ad_cost_per_order))

    def money(value: Decimal | None) -> float | None:
        return float(cents(value)) if value is not None else None

    return EconomicsResult(
        gross_profit=money(gross),
        gross_margin_percent=money(gross / price * 100) if gross is not None else None,
        payment_fee=money(fee),
        estimated_net_profit=money(net),
        estimated_net_margin_percent=money(net / price * 100) if net is not None else None,
        break_even_ad_cost=money(break_even),
        missing_inputs=[
            field
            for field in (
                "product_cost",
                "selling_price",
                "shipping_cost",
                "payment_fee_percent",
                "estimated_ad_cost_per_order",
            )
            if getattr(inputs, field) is None
        ],
    )
