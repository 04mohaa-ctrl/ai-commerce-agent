"""Explicit V4 tax/FX assumptions; no tax determination or provider requests."""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.services.economics import cents
from src.services.landed_cost import calculate_landed_cost
from src.services.market_economics import MarketEconomicsInputs, MarketEconomicsResult


class TaxAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    price_basis: Literal["UNKNOWN", "VAT_INCLUSIVE", "VAT_EXCLUSIVE", "NO_VAT"] = "UNKNOWN"
    sales_vat_percent: float | None = Field(default=None, ge=0, le=100)
    import_vat_per_unit: float | None = Field(default=None, ge=0, le=1_000_000)
    import_vat_recoverable_percent: float | None = Field(default=None, ge=0, le=100)

    @property
    def unrecoverable_import_vat(self) -> Decimal | None:
        if self.import_vat_per_unit is None:
            return None
        if self.import_vat_per_unit == 0:
            return Decimal("0")
        if self.import_vat_recoverable_percent is None:
            return None
        return cents(
            Decimal(str(self.import_vat_per_unit))
            * (1 - Decimal(str(self.import_vat_recoverable_percent)) / 100)
        )


class PriceConversion(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    customer_price: Decimal = Field(gt=0, le=1_000_000)
    currency: Literal["SEK", "EUR", "GBP"]
    usd_per_currency: Decimal = Field(gt=0, le=1_000_000)
    rate_date: date
    source: str = Field(min_length=1, max_length=200)

    @field_validator("source")
    @classmethod
    def plain_source(cls, value):
        if any(ord(c) < 32 for c in value) or not value.strip():
            raise ValueError("Describe the public rate source or explicit estimate.")
        return value.strip()

    @property
    def usd_price(self):
        value = cents(self.customer_price * self.usd_per_currency)
        if not Decimal("0.01") <= value <= Decimal("1000000"):
            raise ValueError("Converted USD price must be between 0.01 and 1000000.")
        return value


def calculate_v4_economics(
    inputs: MarketEconomicsInputs,
    tax: TaxAssumptions,
    quantity: int = 1,
    *,
    adopted_freight_total: Decimal | None = None,
) -> MarketEconomicsResult:
    """Landed cost is per unit; revenue, fees, returns, ads and CPA are per order."""
    if type(quantity) is not int or quantity < 1:
        raise ValueError("Order quantity must be a positive integer.")

    def number(value):
        return Decimal(str(value)) if value is not None else None

    def money(value):
        return float(cents(value)) if value is not None else None

    missing = [f for f, v in inputs.model_dump().items() if v is None]
    base = number(calculate_landed_cost(inputs))
    import_vat = tax.unrecoverable_import_vat
    if tax.import_vat_per_unit is None:
        missing.append("import_vat_per_unit")
    elif import_vat is None:
        missing.append("import_vat_recoverable_percent")
    landed = base + import_vat if base is not None and import_vat is not None else None
    price, rate = number(inputs.selling_price), number(tax.sales_vat_percent)
    net_price = charged = None
    if tax.price_basis == "UNKNOWN":
        missing.append("price_basis")
    elif tax.price_basis == "NO_VAT":
        net_price = charged = price
    elif rate is None:
        missing.append("sales_vat_percent")
    elif price is not None:
        net_price = price / (1 + rate / 100) if tax.price_basis == "VAT_INCLUSIVE" else price
        charged = price if tax.price_basis == "VAT_INCLUSIVE" else price * (1 + rate / 100)
    revenue = net_price * quantity if net_price is not None else None
    fee, fixed = number(inputs.payment_fee_percent), number(inputs.payment_fixed_fee)
    payment = (
        cents(charged * quantity * fee / 100 + fixed)
        if charged is not None and fee is not None and fixed is not None
        else None
    )
    returns = (
        cents(number(inputs.return_rate_percent) / 100 * number(inputs.estimated_loss_per_return))
        if inputs.return_rate_percent is not None and inputs.estimated_loss_per_return is not None
        else None
    )
    order_landed = landed * quantity if landed is not None else None
    if order_landed is not None and adopted_freight_total is not None:
        # The adopted per-unit display is cent-rounded. Charge the exact quote once per order.
        order_landed += (
            adopted_freight_total - number(inputs.international_shipping_per_unit) * quantity
        )
    gross = revenue - order_landed if revenue is not None and order_landed is not None else None
    contribution = (
        gross - payment - returns
        if gross is not None and payment is not None and returns is not None
        else None
    )
    ads = number(inputs.estimated_ad_cost_per_order)
    net = contribution - ads if contribution is not None and ads is not None else None
    return MarketEconomicsResult(
        revenue_per_order=money(revenue),
        landed_cost=money(landed),
        gross_profit_before_marketing=money(gross),
        payment_cost=money(payment),
        expected_return_cost=money(returns),
        contribution_before_ads=money(contribution),
        estimated_ad_cost=money(ads),
        estimated_net_profit=money(net),
        estimated_net_margin_percent=float(net / revenue * 100)
        if net is not None and revenue is not None and revenue > 0
        else None,
        break_even_ad_cost=money(contribution),
        missing_inputs=missing,
    )
