"""Native-currency Product/Offer parsing and statistics; never performs network I/O."""

import json
from datetime import datetime, timezone
from decimal import Decimal
from statistics import median
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from src.research.matching import MatchOutcome, discriminators, match_product, normalized_name
from src.research.models import Source, canonical_url
from src.research.providers.prices import JsonLdParser
from src.schemas.product import Product


class MarketPriceObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    product_name: str
    retailer: str
    price: Decimal = Field(gt=0, le=1_000_000)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    shipping_price: Decimal | None = Field(default=None, ge=0, le=1_000_000)
    observed_at: datetime
    url: str
    source_id: str
    availability: str = "Unknown"
    variant: str = ""
    brand: str | None = None
    match_outcome: MatchOutcome
    match_reasons: list[str] = Field(default_factory=list)
    reviewed: bool = False

    @field_validator("url")
    @classmethod
    def valid_url(cls, value):
        return canonical_url(value)

    @field_validator("observed_at")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError("Observation time needs a timezone.")
        return value.astimezone(timezone.utc)


class PriceSummary(BaseModel):
    product_name: str
    currency: str
    variant: str = ""
    brand: str | None = None
    count: int
    minimum: Decimal | None = None
    median: Decimal | None = None
    maximum: Decimal | None = None
    observed_at: list[datetime] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)
    notice: str = "Insufficient price observations"


def _text(value):
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return _text(value.get("name"))
    return ""


def extract_market_prices(
    html: str, product: Product, source: Source
) -> list[MarketPriceObservation]:
    parser = JsonLdParser()
    parser.feed(html)
    rows = []

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            kinds = node.get("@type", [])
            kinds = kinds if isinstance(kinds, list) else [kinds]
            if "Product" in [str(k).rsplit("/", 1)[-1] for k in kinds]:
                parse_product(node)
            for child in node.values():
                if isinstance(child, (dict, list)):
                    walk(child)

    def parse_product(node):
        name, brand = _text(node.get("name")), _text(node.get("brand")) or None
        if not name:
            return
        details = []
        for key in ("size", "color", "model", "sku"):
            value = _text(node.get(key))
            if value:
                details.append(f"{key}={value}")
        if node.get("isVariantOf"):
            details.append("variant-of=" + _text(node["isVariantOf"]))
        pack = node.get("numberOfItems")
        pack_text = f"{pack} pack" if isinstance(pack, (int, str)) and str(pack).isdigit() else ""
        if pack_text:
            details.append("count=" + str(pack))
        variant = "; ".join(details)
        matching_name = name
        for value in [_text(node.get(k)) for k in ("size", "color")] + [pack_text]:
            if value and normalized_name(value) not in normalized_name(name):
                matching_name += " " + value
        match = match_product(product, matching_name.strip(), brand=brand)
        model = normalized_name(_text(node.get("model")))
        if model and f" {model} " not in f" {normalized_name(product.name)} ":
            if match.outcome != "NO_MATCH":
                match.outcome = "AMBIGUOUS"
                match.reasons.append("Requested product does not specify this model variant.")
        offers = node.get("offers", [])
        offers = offers if isinstance(offers, list) else [offers]
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            kind = offer.get("@type", "Offer")
            if isinstance(kind, list):
                is_offer = "Offer" in kind
            else:
                is_offer = str(kind).rsplit("/", 1)[-1] == "Offer"
            if not is_offer:
                continue
            currency = offer.get("priceCurrency")
            shipping = None
            ship = offer.get("shippingDetails")
            if isinstance(ship, dict):
                rate = ship.get("shippingRate")
                if isinstance(rate, dict) and rate.get("currency") == currency:
                    shipping = rate.get("value")
            try:
                rows.append(
                    MarketPriceObservation(
                        product_name=name,
                        retailer=urlsplit(source.url).hostname or source.title,
                        price=offer.get("price"),
                        currency=currency,
                        shipping_price=shipping,
                        observed_at=source.accessed_at,
                        url=source.url,
                        source_id=source.id,
                        availability=_text(offer.get("availability")).rsplit("/", 1)[-1]
                        or "Unknown",
                        variant=variant,
                        brand=brand,
                        match_outcome=match.outcome,
                        match_reasons=match.reasons,
                    )
                )
            except ValidationError:
                continue

    for block in parser.blocks:
        try:
            walk(json.loads(block))
        except (ValueError, RecursionError):
            continue
    return list(
        {(r.url, r.product_name, r.variant, r.brand, r.price, r.currency): r for r in rows}.values()
    )


def summarize_prices(observations: list[MarketPriceObservation]) -> list[PriceSummary]:
    groups = {}
    for row in observations:
        if row.availability.casefold() not in {"instock", "limitedavailability", "available"}:
            continue
        if row.match_outcome != "MATCH" and not (
            row.match_outcome == "LIKELY_MATCH" and row.reviewed
        ):
            continue
        identity = (
            normalized_name(row.product_name),
            row.currency,
            normalized_name(row.brand or ""),
            normalized_name(row.variant),
            tuple(discriminators(row.product_name).items()),
        )
        groups.setdefault(identity, []).append(row)
    summaries = []
    for rows in groups.values():
        by_url = {}
        conflicts = set()
        for row in rows:
            url = canonical_url(row.url)
            if url in by_url and by_url[url].price != row.price:
                conflicts.add(url)
            by_url[url] = row
        unique = [row for url, row in by_url.items() if url not in conflicts]
        prices = [r.price for r in unique]
        example = rows[0]
        enough = len(prices) >= 2
        summaries.append(
            PriceSummary(
                product_name=example.product_name,
                currency=example.currency,
                variant=example.variant,
                brand=example.brand,
                count=len(prices),
                minimum=min(prices) if enough else None,
                median=median(prices) if enough else None,
                maximum=max(prices) if enough else None,
                observed_at=[r.observed_at for r in unique],
                source_ids=list(dict.fromkeys(r.source_id for r in unique)),
                urls=list(dict.fromkeys(r.url for r in unique)),
                notice="Compatible available listing prices; inspect identity and dates."
                if enough
                else "Insufficient price observations",
            )
        )
    return summaries
