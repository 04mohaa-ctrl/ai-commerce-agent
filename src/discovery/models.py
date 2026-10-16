"""Catalog prices are observations, never adopted variant costs."""

import re
from datetime import datetime
from decimal import Decimal

from pydantic import Field, field_validator, model_validator

from src.supply.models import (
    ActionTelemetry,
    Country,
    Money,
    ProviderOutcome,
    SupplierProductCandidate,
    SupplyModel,
)


class DiscoverySearch(SupplyModel):
    query: str = Field(min_length=1, max_length=200)
    page: int = Field(default=1, strict=True, ge=1, le=2)
    size: int = Field(default=10, strict=True, ge=1, le=10)
    country: Country | None = None
    category_id: str | None = Field(default=None, min_length=1, max_length=200)
    min_price: Money | None = None
    max_price: Money | None = None

    @field_validator("query", "category_id")
    @classmethod
    def plain(cls, value):
        if value is not None and any(ord(c) < 32 for c in value):
            raise ValueError("Search requires plain text.")
        return value

    @field_validator("min_price", "max_price", mode="before")
    @classmethod
    def numeric(cls, value):
        if isinstance(value, bool):
            raise ValueError("Price must be numeric.")
        return value

    @model_validator(mode="after")
    def ordered(self):
        if self.min_price is not None and self.max_price is not None:
            if self.min_price > self.max_price:
                raise ValueError("Minimum price exceeds maximum price.")
        return self

    def parameters(self):
        params = {"keyWord": self.query, "page": self.page, "size": self.size}
        for field, name in (
            ("country", "countryCode"),
            ("category_id", "categoryId"),
            ("min_price", "startSellPrice"),
            ("max_price", "endSellPrice"),
        ):
            value = getattr(self, field)
            if value is not None:
                params[name] = str(value)
        return params


def catalog_price(value):
    """Accept documented USD sellPrice scalars/ranges; reject malformed optional fields."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return None
    text = str(value).strip()
    if len(text) > 60 or not re.fullmatch(r"\d+(?:\.\d+)?(?:\s*-\s*\d+(?:\.\d+)?)?", text):
        return None
    values = [Decimal(part.strip()) for part in text.split("-")]
    if any(v > 1_000_000 for v in values) or values[0] > values[-1]:
        return None
    return text


class CatalogItem(SupplyModel):
    candidate: SupplierProductCandidate
    catalog_price: str | None = None
    currency: str | None = None
    evidence_kind: str = "provider_observation"

    @field_validator("catalog_price")
    @classmethod
    def price(cls, value):
        if value is not None and catalog_price(value) is None:
            raise ValueError("Invalid catalog price.")
        return value

    @model_validator(mode="after")
    def currency_required(self):
        if self.catalog_price is not None and self.currency != "USD":
            raise ValueError("CJ sellPrice requires documented USD semantics.")
        return self


class DiscoveryResult(SupplyModel):
    search: DiscoverySearch
    outcome: ProviderOutcome
    telemetry: ActionTelemetry
    cached: bool = False
    searched_at: datetime
