"""Explicit per-unit landed costs; unknown components never become zero."""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator

from src.services.economics import Cost, cents

LANDED_COST_FIELDS = (
    "unit_product_cost",
    "international_shipping_per_unit",
    "import_duty_per_unit",
    "customs_fee_per_unit",
    "packaging_per_unit",
    "handling_per_unit",
    "other_variable_cost_per_unit",
)


class LandedCostInputs(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    unit_product_cost: Cost | None = None
    international_shipping_per_unit: Cost | None = None
    import_duty_per_unit: Cost | None = None
    customs_fee_per_unit: Cost | None = None
    packaging_per_unit: Cost | None = None
    handling_per_unit: Cost | None = None
    other_variable_cost_per_unit: Cost | None = None

    @field_validator(*LANDED_COST_FIELDS)
    @classmethod
    def round_landed_currency(cls, value: float | None) -> float | None:
        return float(cents(Decimal(str(value)))) if value is not None else None


def calculate_landed_cost(inputs: LandedCostInputs) -> float | None:
    """Return a cent-rounded total only when every component is explicitly known."""
    values = [getattr(inputs, field) for field in LANDED_COST_FIELDS]
    if any(value is None for value in values):
        return None
    return float(cents(sum((Decimal(str(value)) for value in values), Decimal("0"))))
