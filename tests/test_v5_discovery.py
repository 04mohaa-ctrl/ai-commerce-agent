"""Synthetic CJ-shaped fixtures; no live catalog or demand claims."""

from datetime import UTC, datetime, timedelta

import pytest

from src.database.database import ProductRepository
from src.supply.models import Destination
from tests.test_cj_provider import provider_for


def catalog_rows():
    return {
        "content": [
            {
                "productList": [
                    {
                        "id": "p1",
                        "nameEn": "Laptop stand",
                        "sellPrice": "4.00-8.00",
                        "bigImage": "https://images.example/stand.jpg",
                    },
                    {"id": "p2", "nameEn": "Pet brush", "sellPrice": "3.25"},
                    {"id": "p3", "nameEn": "Lunch box", "sellPrice": "not-a-price"},
                    {"nameEn": "Broken identity"},
                ]
            }
        ]
    }


def test_catalog_filters_prices_and_partial_records(monkeypatch):
    from src.discovery.models import DiscoverySearch

    provider, requests = provider_for(monkeypatch, catalog_rows())
    search = DiscoverySearch(query="stand", country="CN", min_price=2, max_price=10)
    outcome = provider.discover(search)
    assert outcome.status == "SUCCESS" and outcome.partial
    assert len(outcome.records) == 3
    assert outcome.records[0]["catalog_price"] == "4.00-8.00"
    assert outcome.records[0]["currency"] == "USD"
    assert outcome.records[2]["catalog_price"] is None
    assert requests[-1].url.params["countryCode"] == "CN"
    assert requests[-1].url.params["startSellPrice"] == "2"
    assert "orderBy" not in requests[-1].url.params


@pytest.mark.parametrize(
    "overrides",
    [
        {"page": 3},
        {"size": 11},
        {"query": ""},
        {"min_price": 10, "max_price": 2},
        {"country": "xx"},
        {"min_price": True},
    ],
)
def test_search_bounds(overrides):
    from src.discovery.models import DiscoverySearch

    with pytest.raises(ValueError):
        DiscoverySearch(**({"query": "brush"} | overrides))


def test_saved_identity_duplicate_names_and_restart(tmp_path):
    from src.discovery.models import CatalogItem
    from src.discovery.repository import DiscoveryRepository
    from src.discovery.service import save_candidate
    from src.supply.models import SupplierProductCandidate

    repo = ProductRepository(tmp_path / "catalog.db")
    extension = DiscoveryRepository(repo)

    def item(pid):
        return CatalogItem(
            candidate=SupplierProductCandidate(
                provider="cj", product_id=pid, name="Same product name"
            )
        )

    first = save_candidate(repo, item("a"), Destination(country="SE"))
    duplicate = save_candidate(repo, item("a"), Destination(country="US"))
    other = save_candidate(repo, item("b"), Destination(country="SE"))
    assert first.product.id == duplicate.product.id != other.product.id
    assert len(repo.list_saved()) == 2
    restarted = DiscoveryRepository(ProductRepository(repo.path))
    assert restarted.get_origin(first.product.id).candidate.product_id == "a"
    assert extension.get_origin(other.product.id).candidate.product_id == "b"
    assert first.product.cost is None
    from src.database.supply_repository import SupplyRepository

    assert SupplyRepository(repo).get_settings(first.product.id).country == "SE"


def test_discovery_cache_exact_filters_and_stale(tmp_path, monkeypatch):
    from src.discovery.models import DiscoverySearch
    from src.discovery.service import DiscoveryService

    provider, requests = provider_for(monkeypatch, catalog_rows())
    repo = ProductRepository(tmp_path / "search.db")
    now = datetime.now(UTC)
    service = DiscoveryService(repo, provider, clock=lambda: now)
    search = DiscoverySearch(query="stand")
    first = service.search(search)
    count = len(requests)
    assert first.outcome.partial
    assert service.search(search).cached
    assert len(requests) == count
    service.search(search.model_copy(update={"page": 2}))
    assert len(requests) == count + 1
    now += timedelta(days=2)
    assert not service.search(search).cached
    before = len(requests)
    assert service.search(search, demo=True).outcome.status == "UNAVAILABLE"
    assert len(requests) == before


def test_saved_supplier_research_never_searches_other_products(tmp_path):
    from src.discovery.models import CatalogItem
    from src.discovery.service import save_candidate
    from src.supply.models import SupplierProductCandidate
    from src.supply.service import SupplierIntelligenceService
    from tests.test_supply_pipeline import FixtureSupplier

    repo = ProductRepository(tmp_path / "pinned.db")
    item = CatalogItem(
        candidate=SupplierProductCandidate(
            provider="fixture", product_id="pid1", name="Pet Hair Remover"
        )
    )
    result = save_candidate(repo, item, Destination())
    provider = FixtureSupplier(result.product)
    report = SupplierIntelligenceService(repo, provider).research(result.product, Destination())
    assert "search" not in provider.calls
    assert report.offers[0].variant.product_id == "pid1"
    assert report.offers[0].variant.variant_id == "vid1"


def test_synthetic_saved_identity_cannot_dispatch_live(tmp_path):
    from src.discovery.models import CatalogItem
    from src.discovery.service import save_candidate
    from src.supply.models import SupplierProductCandidate
    from src.supply.service import SupplierIntelligenceService
    from tests.test_supply_pipeline import FixtureSupplier

    repo = ProductRepository(tmp_path / "synthetic.db")
    item = CatalogItem(
        candidate=SupplierProductCandidate(
            provider="fixture", product_id="pid1", name="Pet Hair Remover"
        ),
        evidence_kind="SYNTHETIC",
    )
    result = save_candidate(repo, item, Destination())
    provider = FixtureSupplier(result.product)
    report = SupplierIntelligenceService(repo, provider).research(result.product, Destination())
    assert provider.calls == []
    assert report.stages[0]["status"] == "UNSUPPORTED"


def test_candidate_save_rolls_back_all_product_records_on_failure(tmp_path):
    from src.database.database import DataStoreError
    from src.discovery.models import CatalogItem
    from src.discovery.repository import DiscoveryRepository
    from src.discovery.service import save_candidate
    from src.supply.models import SupplierProductCandidate

    repo = ProductRepository(tmp_path / "atomic.db")
    with repo._connection() as conn:
        conn.execute(
            "CREATE TRIGGER fail_save BEFORE INSERT ON saved_products "
            "BEGIN SELECT RAISE(ABORT,'synthetic storage failure'); END"
        )
    item = CatalogItem(
        candidate=SupplierProductCandidate(provider="cj", product_id="a", name="Brush")
    )
    with pytest.raises(DataStoreError):
        save_candidate(repo, item, Destination())
    assert repo.list_candidates() == []
    with repo._connection() as conn:
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE name='workspace_v5'").fetchone()
        if exists:
            assert (
                conn.execute("SELECT COUNT(*) FROM workspace_v5 WHERE kind='origin'").fetchone()[0]
                == 0
            )
    assert DiscoveryRepository(repo).list_groups() == []
