"""Local estimated seed data and an interface for future external sources."""

import json
from pathlib import Path
from typing import Protocol

from src.config import PROJECT_ROOT
from src.schemas.product import Product


class ProductSource(Protocol):
    def search(self, query: str) -> list[Product]:
        """Return structured candidates with source-supplied evidence, if any."""
        ...


def matches_query(product: Product, query: str) -> bool:
    haystack = " ".join(
        [product.name, product.category, product.description, *product.tags]
    ).casefold()
    return all(token in haystack for token in query.casefold().split())


class LocalProductSource:
    def __init__(self, path: Path | None = None):
        seed_path = path or PROJECT_ROOT / "data" / "demo_products.json"
        self.products = [
            Product.model_validate(row) for row in json.loads(seed_path.read_text(encoding="utf-8"))
        ]

    def search(self, query: str) -> list[Product]:
        return [p.model_copy(deep=True) for p in self.products if matches_query(p, query)]
