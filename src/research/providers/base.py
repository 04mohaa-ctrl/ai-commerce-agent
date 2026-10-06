"""Provider boundary and stable research input identity."""

import hashlib
import json
from collections.abc import Callable
from typing import Protocol

from src.research.models import ResearchReport
from src.schemas.product import Product

ProgressCallback = Callable[[str], None]


class ResearchProviderError(RuntimeError):
    """Sanitized provider failure for presentation and persistence."""

    def __init__(self, message: str, partial_report: ResearchReport | None = None):
        super().__init__(message)
        self.partial_report = partial_report


class ResearchProvider(Protocol):
    def research(
        self, product: Product, progress: ProgressCallback | None = None
    ) -> ResearchReport: ...


def product_fingerprint(product: Product) -> str:
    content = {
        "name": product.name.casefold(),
        "category": product.category.casefold(),
        "description": product.description,
        "tags": sorted(product.tags),
    }
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
