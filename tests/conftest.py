import pytest

from src.schemas.product import Product
from src.services.scoring import build_result


@pytest.fixture
def product():
    return Product(
        name="Pet Hair Remover",
        category="Pet products",
        cost=4,
        selling_price=20,
        description="Reusable roller for furniture",
        tags=["pet accessories"],
    )


@pytest.fixture
def result(product):
    from src.schemas.product import Assessment

    return build_result(product, Assessment(demand=8, competition=4, trend=7, marketing=9))


@pytest.fixture(autouse=True)
def offline_market_boundaries(monkeypatch):
    """Existing UI fixtures gain V3 stages without making real page/API requests."""
    import httpx

    from src.research.providers.page_verification import PageVerificationProvider
    from src.research.providers.safe_http import SafePageFetcher

    monkeypatch.delenv("DATAFORSEO_LOGIN", raising=False)
    monkeypatch.delenv("DATAFORSEO_PASSWORD", raising=False)
    original = PageVerificationProvider.__init__

    def initialize(self, fetcher=None):
        if fetcher is None:
            fetcher = SafePageFetcher(
                transport=httpx.MockTransport(lambda request: httpx.Response(404)),
                resolver=lambda host: ["93.184.216.34"],
            )
        original(self, fetcher)

    monkeypatch.setattr(PageVerificationProvider, "__init__", initialize)
