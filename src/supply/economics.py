"""Explicit financial revisions and observation applicability, preserving V3 arithmetic."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.services.economics import cents
from src.services.landed_cost import LANDED_COST_FIELDS
from src.services.market_economics import (
    MarketEconomicsInputs,
    MarketEconomicsResult,
)
from src.supply.financial_scenario import PriceConversion, TaxAssumptions, calculate_v4_economics
from src.supply.matching import destination_issue


def utc_now():
    return datetime.now(timezone.utc)


def fresh(timestamp, hours, now):
    return timestamp is not None and timedelta(0) <= now - timestamp <= timedelta(hours=hours)


class FinancialInputProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    value: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    unit: Literal["per_unit", "per_order", "percent"] = "per_unit"
    source_kind: Literal["UNKNOWN", "ESTIMATED", "OBSERVED", "DERIVED"] = "UNKNOWN"
    observation_id: str | None = None
    observed_at: datetime | None = None
    derivation: str = ""

    @field_validator("observed_at")
    @classmethod
    def aware(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Financial observation time requires a timezone.")
        return value.astimezone(timezone.utc) if value else None

    @model_validator(mode="after")
    def observation_required(self):
        if self.source_kind in {"OBSERVED", "DERIVED"} and (
            not self.observation_id or self.observed_at is None or self.value is None
        ):
            raise ValueError("Observed financial values need an observation and timestamp.")
        if self.value is None and self.source_kind != "UNKNOWN":
            raise ValueError("Missing financial input must remain unknown.")
        if self.value is not None and self.source_kind == "UNKNOWN":
            raise ValueError("Known financial input requires provenance.")
        return self


def _manual(field, value, currency):
    return FinancialInputProvenance(
        value=Decimal(str(value)) if value is not None else None,
        currency=currency,
        unit="percent"
        if field.endswith("percent")
        else "per_unit"
        if field in LANDED_COST_FIELDS or field == "selling_price"
        else "per_order",
        source_kind="ESTIMATED" if value is not None else "UNKNOWN",
        derivation="Explicit manual assumption" if value is not None else "Not supplied",
    )


class FinancialSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    inputs: MarketEconomicsInputs = Field(default_factory=MarketEconomicsInputs)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    provenance: dict[str, FinancialInputProvenance] = Field(default_factory=dict)
    revision: int = Field(default=1, ge=1)
    updated_at: datetime = Field(default_factory=utc_now)
    tax_assumptions: TaxAssumptions = Field(default_factory=TaxAssumptions)
    price_conversion: PriceConversion | None = None

    @field_validator("updated_at")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError("Financial revision requires UTC-aware time.")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def own_inputs(self):
        self.inputs = MarketEconomicsInputs.model_validate(self.inputs.model_dump())
        self.tax_assumptions = TaxAssumptions.model_validate(self.tax_assumptions.model_dump())
        if self.price_conversion:
            self.price_conversion = PriceConversion.model_validate(
                self.price_conversion.model_dump()
            )
            if (
                self.currency != "USD"
                or self.inputs.selling_price is None
                or Decimal(str(self.inputs.selling_price)) != self.price_conversion.usd_price
            ):
                raise ValueError("Recorded FX conversion must agree with the USD selling price.")
        self.provenance = {k: v.model_copy(deep=True) for k, v in self.provenance.items()}
        if set(self.provenance) - set(MarketEconomicsInputs.model_fields):
            raise ValueError("Unknown financial provenance field.")
        for field, value in self.inputs.model_dump().items():
            self.provenance.setdefault(field, _manual(field, value, self.currency))
            if field == "selling_price" and self.provenance[field].unit == "per_order":
                self.provenance[field].unit = "per_unit"
                self.provenance[
                    field
                ].derivation += (
                    "; V4 per-unit selling price; legacy per_order metadata normalized on read"
                )
            expected = Decimal(str(value)) if value is not None else None
            if self.provenance[field].value != expected:
                raise ValueError("Financial input does not agree with provenance.")
            expected_unit = (
                "percent"
                if field.endswith("_percent")
                else "per_unit"
                if field in LANDED_COST_FIELDS or field == "selling_price"
                else "per_order"
            )
            if self.provenance[field].unit != expected_unit:
                raise ValueError("Financial provenance unit does not agree with its input field.")
        return self


class FinancialCalculation(BaseModel):
    revision: int
    currency: str
    economics: MarketEconomicsResult | None
    landed_cost_per_order: float | None = None
    known_cost_subtotal: Decimal
    missing_inputs: list[str]
    compatible: bool
    current: bool
    reasons: list[str]


def selection_issue(selection, destination=None):
    if selection is None:
        return "No compatible selected supplier."
    offer = selection.offer
    if offer.match.outcome not in {"MATCH", "LIKELY_MATCH"} or offer.match.contradictions:
        return "Selected product identity is ambiguous or incompatible."
    if offer.match.missing_attributes:
        return "Decisive product attributes are missing."
    if destination is not None:
        if issue := destination_issue(offer.candidate, offer.variant, destination):
            return issue
    if (offer.candidate.provider, offer.candidate.product_id) != (
        offer.variant.provider,
        offer.variant.product_id,
    ):
        return "Supplier product and variant identities disagree."
    if offer.match.outcome == "LIKELY_MATCH":
        actual = offer.variant.attributes
        confirmed = selection.confirmed_attributes
        if (
            not actual
            or not confirmed
            or any(confirmed.get(k) != v for k, v in actual.items())
            or any(k not in actual for k in confirmed)
        ):
            return "Likely matches require explicit confirmation of observed variant attributes."
    return None


def component_state(component, selection, stages):
    """Latest applicable component attempt; unrelated candidate failures do not leak."""
    if selection is None:
        return None
    offer = selection.offer
    expected = {
        "provider": offer.variant.provider,
        "product_id": offer.variant.product_id,
        "variant_id": offer.variant.variant_id,
        "warehouse_id": offer.stock.warehouse_id if offer.stock else None,
        "storage_id": offer.stock.storage_id if offer.stock else None,
    }
    relevant = []
    for stage in stages or []:
        if stage.get("component", stage.get("stage")) != component:
            continue
        if any(stage.get(k) is not None and stage[k] != v for k, v in expected.items()):
            continue
        relevant.append(stage)
    return relevant[-1] if relevant else None


def component_issue(component, selection, stages):
    stage = component_state(component, selection, stages)
    if not stage:
        return None
    if stage.get("pending") or stage.get("partial") or stage.get("status") not in {"SUCCESS"}:
        return f"Current {component} evidence is {stage.get('status', 'unavailable').lower()}."
    current = {
        "variants": selection.offer.variant,
        "details": selection.offer.candidate,
        "stock": selection.offer.stock,
        "shipping": selection.offer.quote,
    }.get(component)
    if stage.get("observation_id") and current and stage["observation_id"] != current.id:
        return f"Selected {component} observation is historical; adoption is explicit."
    return None


def supplier_cost_issue(selection, currency, now, stages=(), destination=None):
    issue = selection_issue(selection, destination)
    if issue:
        return issue
    for component in ("details", "variants"):
        if issue := component_issue(component, selection, stages):
            return issue
    variant = selection.offer.variant
    if not fresh(variant.observed_at, 24, now):
        return "Selected supplier cost is stale."
    if variant.unit_price is None:
        return "Selected supplier unit cost is unknown."
    if variant.currency != currency:
        return "Supplier currency is incompatible; no currency conversion is available."
    return None


def stock_issue(selection, destination, now, stages=()):
    if issue := selection_issue(selection, destination):
        return issue
    if issue := component_issue("stock", selection, stages):
        return issue
    variant, stock = selection.offer.variant, selection.offer.stock
    if not stock or not fresh(stock.observed_at, 6, now):
        return "Selected stock is unavailable or stale."
    if (stock.provider, stock.product_id, stock.variant_id) != (
        variant.provider,
        variant.product_id,
        variant.variant_id,
    ):
        return "Stock refers to a different selected variant."
    if stock.quantity is None:
        return "Selected stock quantity is unknown."
    return None


def shipping_issue(selection, destination, currency, now, stages=()):
    if issue := selection_issue(selection, destination):
        return issue
    if issue := component_issue("shipping", selection, stages):
        return issue
    if issue := component_issue("stock", selection, stages):
        return issue
    variant, stock, quote = selection.offer.variant, selection.offer.stock, selection.offer.quote
    if (
        not quote
        or not fresh(quote.observed_at, 6, now)
        or (quote.expires_at and quote.expires_at <= now)
    ):
        return "Shipping quote is missing, stale or expired."
    if (
        not stock
        or not fresh(stock.observed_at, 6, now)
        or not stock.storage_id
        or not stock.country
    ):
        return "Shipping quote cannot be bound to a current selected warehouse."
    if (quote.provider, quote.product_id, quote.variant_id) != (
        variant.provider,
        variant.product_id,
        variant.variant_id,
    ):
        return "Shipping quote refers to a different variant."
    if quote.variant_snapshot != variant.id:
        return "Shipping quote parcel observation differs from the selected variant snapshot."
    if (stock.provider, stock.product_id, stock.variant_id) != (
        variant.provider,
        variant.product_id,
        variant.variant_id,
    ):
        return "Shipping stock refers to a different variant."
    if (quote.warehouse_id, quote.storage_id, quote.origin) != (
        stock.warehouse_id,
        stock.storage_id,
        stock.country,
    ):
        return "Shipping quote warehouse, storage or origin does not match."
    for field in ("country", "quantity", "postal_code", "region"):
        if getattr(quote.destination, field) != getattr(destination, field):
            return "Shipping quote destination or quantity does not match."
    if quote.quantity != destination.quantity:
        return "Shipping quote quantity does not match."
    if quote.total_cost is None or quote.currency != currency:
        return "Shipping price is unknown or currency is incompatible."
    return None


def _applied(snapshot, field, value, observation, derivation, now):
    payload = snapshot.inputs.model_dump()
    payload[field] = float(cents(value))
    provenance = dict(snapshot.provenance)
    provenance[field] = FinancialInputProvenance(
        value=cents(value),
        currency=observation.currency,
        source_kind="DERIVED" if derivation else "OBSERVED",
        unit="per_unit",
        observation_id=observation.id,
        observed_at=observation.observed_at,
        derivation=derivation or "Explicitly adopted observed supplier unit price",
    )
    return FinancialSnapshot(
        inputs=MarketEconomicsInputs(**payload),
        tax_assumptions=snapshot.tax_assumptions,
        price_conversion=snapshot.price_conversion,
        currency=snapshot.currency,
        provenance=provenance,
        revision=snapshot.revision + 1,
        updated_at=now,
    )


def apply_supplier_cost(snapshot, selection, destination, now=None, *, stages=()):
    now = now or utc_now()
    if issue := supplier_cost_issue(selection, snapshot.currency, now, stages, destination):
        raise ValueError(issue)
    variant = selection.offer.variant
    return _applied(snapshot, "unit_product_cost", variant.unit_price, variant, "", now)


def apply_shipping_cost(snapshot, selection, destination, now=None, *, stages=()):
    now = now or utc_now()
    if issue := shipping_issue(selection, destination, snapshot.currency, now, stages):
        raise ValueError(issue)
    quote = selection.offer.quote
    return _applied(
        snapshot,
        "international_shipping_per_unit",
        quote.total_cost / quote.quantity,
        quote,
        f"Quote total {quote.total_cost} / {quote.quantity} units; explicitly adopted",
        now,
    )


def save_manual_inputs(snapshot, inputs):
    inputs = MarketEconomicsInputs.model_validate(inputs.model_dump())
    provenance = dict(snapshot.provenance)
    for field, value in inputs.model_dump().items():
        if getattr(snapshot.inputs, field) != value:
            provenance[field] = _manual(field, value, snapshot.currency)
    return FinancialSnapshot(
        inputs=inputs,
        tax_assumptions=snapshot.tax_assumptions,
        price_conversion=snapshot.price_conversion
        if inputs.selling_price == snapshot.inputs.selling_price
        else None,
        currency=snapshot.currency,
        provenance=provenance,
        revision=snapshot.revision + 1,
        updated_at=utc_now(),
    )


def save_tax_assumptions(snapshot, tax):
    payload = snapshot.model_dump()
    payload.update(
        tax_assumptions=tax.model_dump(), revision=snapshot.revision + 1, updated_at=utc_now()
    )
    return FinancialSnapshot.model_validate(payload)


def save_customer_price(snapshot, conversion):
    inputs = snapshot.inputs.model_copy(update={"selling_price": float(conversion.usd_price)})
    updated = save_manual_inputs(snapshot, inputs)
    updated.price_conversion = conversion
    updated.provenance["selling_price"].derivation = (
        f"Explicit manual FX: {conversion.customer_price} {conversion.currency} × "
        f"{conversion.usd_per_currency} USD/{conversion.currency}; "
        f"rate date {conversion.rate_date}; source {conversion.source}"
    )
    return FinancialSnapshot.model_validate(updated.model_dump())


def calculate_financial(snapshot, selection=None, destination=None, stages=(), now=None):
    now = now or utc_now()
    compatible, current = True, True
    reasons = []
    known = Decimal("0")
    missing = []
    for field, value in snapshot.inputs.model_dump().items():
        source = snapshot.provenance[field]
        valid = True
        if value is None:
            missing.append(field)
        if source.value != (Decimal(str(value)) if value is not None else None):
            valid = False
            compatible = False
            reasons.append(f"{field}: input differs from its recorded provenance.")
        if (
            value is not None
            and not field.endswith("_percent")
            and source.currency != snapshot.currency
        ):
            valid = False
            compatible = False
            reasons.append(f"{field}: incompatible currency.")
        if source.source_kind in {"OBSERVED", "DERIVED"}:
            ttl = 6 if field == "international_shipping_per_unit" else 24
            if not fresh(source.observed_at, ttl, now):
                valid = False
                current = False
                reasons.append(f"{field}: adopted observation is stale.")
            if selection is None or destination is None:
                valid = False
                current = False
                reasons.append(
                    f"{field}: current selected observation and destination binding required."
                )
            if selection is not None:
                observation = (
                    selection.offer.quote
                    if field == "international_shipping_per_unit"
                    else selection.offer.variant
                )
                if not observation or observation.id != source.observation_id:
                    valid = False
                    current = False
                    reasons.append(f"{field}: adopted observation differs from selected snapshot.")
                elif destination is not None:
                    issue = (
                        shipping_issue(selection, destination, snapshot.currency, now, stages)
                        if field == "international_shipping_per_unit"
                        else supplier_cost_issue(
                            selection, snapshot.currency, now, stages, destination
                        )
                    )
                    if issue:
                        valid = False
                        current = False
                        reasons.append(f"{field}: {issue}")
        if valid and field in LANDED_COST_FIELDS and value is not None:
            known += Decimal(str(value))
    tax_cost = snapshot.tax_assumptions.unrecoverable_import_vat
    if tax_cost is not None:
        known += tax_cost
    freight_source = snapshot.provenance["international_shipping_per_unit"]
    exact_freight = (
        selection.offer.quote.total_cost
        if compatible
        and current
        and selection
        and selection.offer.quote
        and freight_source.source_kind in {"OBSERVED", "DERIVED"}
        else None
    )
    computed = calculate_v4_economics(
        snapshot.inputs,
        snapshot.tax_assumptions,
        destination.quantity if destination else 1,
        adopted_freight_total=exact_freight,
    )
    missing = computed.missing_inputs
    economics = computed if compatible and current else None
    quantity = destination.quantity if destination else 1
    order_landed = (
        Decimal(str(economics.landed_cost)) * quantity
        if (economics and economics.landed_cost is not None)
        else None
    )
    if order_landed is not None and exact_freight is not None:
        order_landed += (
            exact_freight - Decimal(str(snapshot.inputs.international_shipping_per_unit)) * quantity
        )
    return FinancialCalculation(
        revision=snapshot.revision,
        currency=snapshot.currency,
        economics=economics,
        landed_cost_per_order=float(cents(order_landed)) if order_landed is not None else None,
        known_cost_subtotal=cents(known),
        missing_inputs=missing,
        compatible=compatible,
        current=current,
        reasons=reasons,
    )
