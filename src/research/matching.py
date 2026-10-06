"""Explainable conservative identity matching; keyword similarity needs review."""

import re
import unicodedata
from typing import Literal

from pydantic import BaseModel

from src.schemas.product import Product

MatchOutcome = Literal["MATCH", "LIKELY_MATCH", "AMBIGUOUS", "NO_MATCH"]
COLORS = {
    "red",
    "blue",
    "black",
    "white",
    "green",
    "yellow",
    "pink",
    "purple",
    "orange",
    "grey",
    "gray",
}


def normalized_name(value: str) -> str:
    return " ".join(re.findall(r"[\w]+", unicodedata.normalize("NFKC", value).casefold()))


def discriminators(value: str) -> dict[str, tuple[str, ...]]:
    value = unicodedata.normalize("NFKC", value).casefold()
    packs = re.findall(r"\b(\d+)\s*[- ]?\s*(?:pack|count|pcs|pieces|ct)\b", value)
    packs += re.findall(r"\b(?:pack|set)\s+of\s+(\d+)\b", value)
    capacities = re.findall(
        r"\b(\d+(?:\.\d+)?)\s*(ml|liters?|litres?|l|oz|g|kg|cm|mm|inch(?:es)?)\b", value
    )
    colors = sorted(set(normalized_name(value).split()) & COLORS)
    return {
        "pack": tuple(sorted(set(packs))),
        "size": tuple(sorted({f"{n}{unit}" for n, unit in capacities})),
        "color": tuple(colors),
    }


class MatchResult(BaseModel):
    outcome: MatchOutcome
    reasons: list[str]


def match_product(product: Product, listing_name: str, brand: str | None = None) -> MatchResult:
    expected, actual = normalized_name(product.name), normalized_name(listing_name)
    if not actual:
        return MatchResult(outcome="NO_MATCH", reasons=["Listing has no identity."])
    wanted = discriminators(product.name)
    found = discriminators(listing_name)
    absent = []
    for field in wanted:
        if wanted[field] and found[field] and wanted[field] != found[field]:
            return MatchResult(outcome="NO_MATCH", reasons=[f"Conflicting {field} details."])
        if bool(wanted[field]) != bool(found[field]):
            absent.append(field)
    explicit = re.search(r"(?:^|[;\n])\s*brand\s*:\s*([^;\n,.]+)", product.description, re.I)
    expected_brand = normalized_name(explicit.group(1)) if explicit else None
    listed_brand = normalized_name(brand) if brand else None
    if expected_brand and listed_brand and expected_brand != listed_brand:
        return MatchResult(outcome="NO_MATCH", reasons=["Conflicting explicit brands."])
    if expected_brand and (not listed_brand and f" {expected_brand} " not in f" {actual} "):
        absent.append("brand")
    elif listed_brand and not expected_brand and f" {listed_brand} " not in f" {expected} ":
        absent.append("brand")
    expected_words, actual_words = set(expected.split()), set(actual.split())
    overlap = len(expected_words & actual_words) / max(1, len(expected_words))
    if (
        absent
        and len(expected_words & actual_words) / max(1, min(len(expected_words), len(actual_words)))
        >= 0.67
    ):
        return MatchResult(
            outcome="AMBIGUOUS", reasons=["Missing comparable " + ", ".join(absent) + " details."]
        )
    if overlap < 0.67:
        return MatchResult(outcome="NO_MATCH", reasons=["Insufficient product identity overlap."])
    if absent:
        return MatchResult(
            outcome="AMBIGUOUS", reasons=["Missing comparable " + ", ".join(absent) + " details."]
        )
    if expected == actual:
        return MatchResult(
            outcome="MATCH",
            reasons=["Exact normalized name and compatible explicit discriminators."],
        )
    return MatchResult(
        outcome="LIKELY_MATCH", reasons=["Keyword similarity only; explicit review required."]
    )
