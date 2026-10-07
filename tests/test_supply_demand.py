"""Demand actions preserve measurements while keeping failed/empty current states honest."""

import hashlib
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from src.database.database import ProductRepository
from src.database.market_repository import MarketIntelligenceRepository
from src.database.supply_repository import SupplyRepository
from src.research.models import utc_now
from src.research.providers.base import product_fingerprint
from src.research.providers.demand_trend import DemandObservation, DemandResult
from src.supply.models import Destination

NOW = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)


class FixtureDemand:
    name = "fixture-demand"
    location = "United States (2840)"
    enabled = True
    request_count = 0
    status = "completed"
    empty = False

    def __init__(self, clock=lambda: NOW):
        self.clock = clock
        self.queries = []

    def collect(self, product):
        self.request_count += 1
        self.queries.append(product.name)
        now = self.clock()
        observations = []
        if self.status == "completed" and not self.empty:
            observations = [
                DemandObservation(
                    metric_name="keyword_popularity",
                    provider=self.name,
                    query=product.name,
                    value=40 if index < 3 else 60,
                    unit="relative_popularity_index",
                    period_start=now.date() - timedelta(days=42 - index * 7),
                    period_end=now.date() - timedelta(days=36 - index * 7),
                    collected_at=now,
                    source_url="https://dataforseo.com/",
                    location=self.location,
                    series_id="fixture-series",
                )
                for index in range(6)
            ]
        return DemandResult(
            provider=self.name,
            query=product.name,
            location=self.location,
            status=self.status,
            collected_at=now,
            observations=observations,
        )


@pytest.fixture
def repository(tmp_path):
    legacy = ProductRepository(tmp_path / "d.db")
    MarketIntelligenceRepository(legacy, backup_dir=tmp_path / "b3").enable()
    return SupplyRepository(legacy, backup_dir=tmp_path / "b4")


def service(repository, provider=None, clock=lambda: NOW):
    from src.supply.demand import DemandIntelligenceService

    return DemandIntelligenceService(repository, provider=provider, clock=clock)


def test_demand_refresh_without_openai_persists_actual_requests_and_current_series(
    repository, product
):
    demand = service(repository, FixtureDemand())
    result = demand.refresh(product, Destination(), action_id="demand-one")
    assert result.outcome.status == "SUCCESS"
    assert result.current_eligible and not result.retained
    assert result.trend.classification == "STRONGLY_GROWING"
    assert result.telemetry.requests == {"fixture-demand": 1}
    assert repository.get_latest_action(product.id).action_id == "demand-one"
    reopened = SupplyRepository(ProductRepository(repository.path))
    current = service(reopened, FixtureDemand()).get_current(product, Destination())
    assert current.demand.observations[0].collected_at == NOW
    assert current.telemetry.action_id == "demand-one"


def test_cached_actions_keep_collection_time_and_do_not_repeat_paid_requests(repository, product):
    clock = [NOW]
    provider = FixtureDemand(lambda: clock[0])
    demand = service(repository, provider, lambda: clock[0])
    first = demand.refresh(product, Destination(), action_id="first")
    clock[0] += timedelta(days=6)
    cached = demand.refresh(product, Destination(), action_id="second")
    assert cached.demand.collected_at == first.demand.collected_at
    assert cached.telemetry.requests == {"fixture-demand": 0}
    assert cached.telemetry.cache_hits == ["demand"]
    assert cached.telemetry.action_id == "second"
    clock[0] += timedelta(days=1)
    fresh = demand.refresh(product, Destination(), action_id="third")
    assert fresh.demand.collected_at == clock[0]
    assert provider.request_count == 2


def test_successful_empty_clears_current_series_and_failure_never_resurrects_it(
    repository, product
):
    provider = FixtureDemand()
    demand = service(repository, provider)
    demand.refresh(product, Destination())
    provider.empty = True
    empty = demand.refresh(product, Destination(), force=True)
    assert empty.outcome.status == "SUCCESS_EMPTY"
    assert not empty.demand.observations
    assert not empty.retained and not empty.current_eligible
    provider.status = "failed"
    failed = demand.refresh(product, Destination(), force=True)
    assert failed.outcome.status == "FAILED"
    assert not failed.demand.observations and not failed.retained


def test_failure_keeps_original_observations_labeled_historical_but_not_scored(repository, product):
    provider = FixtureDemand()
    demand = service(repository, provider)
    first = demand.refresh(product, Destination())
    provider.status = "failed"
    failed = demand.refresh(product, Destination(), force=True)
    assert failed.retained and not failed.current_eligible
    assert failed.demand == first.demand
    assert failed.outcome.status == "FAILED"
    assert failed.trend.classification == "INSUFFICIENT_DATA"
    assert failed.telemetry.stages[-1]["retained"]
    assert failed.telemetry.stages[-1]["status"] == "FAILED"


@pytest.mark.parametrize("changed", ["query", "country", "provider", "fingerprint"])
def test_failed_different_request_does_not_retain_incompatible_measurements(
    repository, product, changed
):
    provider = FixtureDemand()
    demand = service(repository, provider)
    demand.refresh(product, Destination())
    destination, query = Destination(), None
    if changed == "query":
        query = "Different visible query"
    elif changed == "country":
        destination = Destination(country="SE")
        provider.location = "Sweden (2752)"
    elif changed == "provider":
        provider.name = "different-provider"
    else:
        product = product.model_copy(update={"description": "Changed product identity"})
    provider.status = "failed"
    result = demand.refresh(product, destination, query=query, force=True)
    assert not result.retained and not result.current_eligible
    assert not result.demand.observations


def test_explicit_query_is_the_exact_visible_request_and_duplicate_action_is_consumed(
    repository, product
):
    provider = FixtureDemand()
    demand = service(repository, provider)
    result = demand.refresh(
        product, Destination(), query="Acme Heated Lunch Box", action_id="same-action"
    )
    duplicate = demand.refresh(
        product, Destination(), query="Acme Heated Lunch Box", force=True, action_id="same-action"
    )
    assert result.demand.query == "Acme Heated Lunch Box"
    assert provider.queries == ["Acme Heated Lunch Box"]
    assert duplicate.telemetry.action_id == result.telemetry.action_id


def test_unknown_country_demo_and_missing_credentials_do_not_dispatch(repository, product):
    provider = FixtureDemand()
    demand = service(repository, provider)
    unknown = demand.refresh(product, Destination(country="ZZ"))
    assert unknown.outcome.status == "UNSUPPORTED"
    demo = demand.refresh(product, Destination(), demo=True)
    assert demo.outcome.status == "UNAVAILABLE"
    assert provider.request_count == 0
    disabled = service(repository).refresh(product, Destination())
    assert disabled.outcome.status == "UNAVAILABLE"
    assert disabled.telemetry.requests == {"dataforseo_trends": 0}


def test_unexpected_provider_failure_is_sanitized_and_not_automatically_retried(
    repository, product
):
    provider = FixtureDemand()

    def fail(product):
        provider.request_count += 1
        raise RuntimeError("fixture-password raw provider failure")

    provider.collect = fail
    demand = service(repository, provider)
    result = demand.refresh(product, Destination())
    assert result.outcome.status == "FAILED"
    assert result.telemetry.requests == {"fixture-demand": 1}
    assert "fixture-password" not in result.model_dump_json()
    cached = demand.refresh(product, Destination())
    assert cached.telemetry.requests == {"fixture-demand": 0}
    assert provider.request_count == 1


@pytest.mark.parametrize("bad", ["query", "location", "provider", "series-query"])
def test_provider_identity_mismatch_does_not_become_current_data(repository, product, bad):
    provider = FixtureDemand()
    collect = provider.collect

    def mismatched(product):
        result = collect(product)
        if bad == "series-query":
            result.observations[0].query = "Wrong query"
        else:
            setattr(result, bad, "Wrong identity")
        return result

    provider.collect = mismatched
    result = service(repository, provider).refresh(product, Destination())
    assert result.outcome.status == "FAILED"
    assert not result.current_eligible and not result.demand.observations


def test_shared_flow_reuses_comparable_v3_demand_without_second_paid_flow(repository, product):
    provider = FixtureDemand()
    original = provider.collect(product)
    provider.request_count = 0
    market = MarketIntelligenceRepository(repository.repository)
    market.save_cache(
        f"demand-v3:{product_fingerprint(product)}:{provider.name}:{provider.location}",
        original.model_dump(mode="json"),
        original.collected_at,
    )
    result = service(repository, provider).refresh(product, Destination())
    assert result.demand == original
    assert result.telemetry.requests == {"fixture-demand": 0}
    assert result.telemetry.cache_hits == ["demand-v3"]


def test_reused_v3_series_keeps_the_original_closed_request_dates(repository, product):
    provider = FixtureDemand(lambda: NOW - timedelta(days=2))
    original = provider.collect(product)
    market = MarketIntelligenceRepository(repository.repository)
    market.save_cache(
        f"demand-v3:{product_fingerprint(product)}:{provider.name}:{provider.location}",
        original.model_dump(mode="json"),
        original.collected_at,
    )
    result = service(repository, provider).refresh(product, Destination())
    assert result.period_start.isoformat() == "2025-10-05"
    assert result.period_end.isoformat() == "2026-10-04"
    assert result.demand.collected_at == original.collected_at


@pytest.mark.parametrize("disabled", ["demo", "credentials"])
def test_disabled_action_keeps_prior_series_historical_without_dispatch(
    repository, product, disabled
):
    provider = FixtureDemand()
    demand = service(repository, provider)
    first = demand.refresh(product, Destination())
    if disabled == "credentials":
        provider.enabled = False
    result = demand.refresh(product, Destination(), demo=disabled == "demo", force=True)
    assert result.retained and result.demand == first.demand
    assert not result.current_eligible and result.outcome.status == "UNAVAILABLE"
    assert provider.request_count == 1
    assert result.telemetry.requests == {"fixture-demand": 0}


def test_generic_unavailable_provider_is_safe_without_a_location_property(repository, product):
    from src.research.providers.demand_trend import UnavailableDemandProvider

    result = service(repository, UnavailableDemandProvider()).refresh(product, Destination())
    assert result.outcome.status == "UNAVAILABLE"
    assert not result.demand.observations
    assert result.telemetry.requests == {"unavailable": 0}


def test_unknown_country_factory_cannot_trigger_v3_default_paid_provider(product):
    from src.supply.demand import demand_provider_for

    provider = demand_provider_for(Destination(country="ZZ"))
    result = provider.collect(product)
    assert result.status == "unavailable" and not result.observations
    assert provider.request_count == 0


@pytest.mark.parametrize("latest", ["empty", "failed"])
def test_newer_v3_attempt_supersedes_fresh_v4_cache_without_second_paid_flow(
    repository, product, latest
):
    clock = [NOW]
    provider = FixtureDemand(lambda: clock[0])
    demand = service(repository, provider, lambda: clock[0])
    demand.refresh(product, Destination())
    clock[0] += timedelta(hours=1)
    result = DemandResult(
        provider=provider.name,
        query=product.name,
        location=provider.location,
        status="completed" if latest == "empty" else "failed",
        collected_at=clock[0],
    )
    MarketIntelligenceRepository(repository.repository).save_cache(
        f"demand-v3:{product_fingerprint(product)}:{provider.name}:{provider.location}",
        result.model_dump(mode="json"),
        result.collected_at,
    )
    current = demand.refresh(product, Destination())
    assert current.outcome.status == ("SUCCESS_EMPTY" if latest == "empty" else "FAILED")
    assert not current.current_eligible
    assert current.retained is (latest == "failed")
    if latest == "empty":
        assert not current.demand.observations
    assert current.telemetry.requests == {"fixture-demand": 0}
    assert provider.request_count == 1


@pytest.mark.parametrize(
    "country,code,name",
    [
        ("US", 2840, "United States"),
        ("GB", 2826, "United Kingdom"),
        ("SE", 2752, "Sweden"),
        ("DE", 2276, "Germany"),
        ("FR", 2250, "France"),
    ],
)
def test_documented_country_mapping_is_sent_once_to_fixed_native_endpoint(
    repository, product, monkeypatch, country, code, name
):
    from src.research.providers.demand_trend import DataForSEOTrendProvider

    monkeypatch.setenv("DATAFORSEO_LOGIN", "fixture-login")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "fixture-password")
    requests = []

    def handler(request):
        requests.append(request)
        body = json.loads(request.content)[0]
        assert body["location_code"] == code
        assert body["keywords"] == [product.name]
        assert body["date_from"] == "2025-10-07" and body["date_to"] == "2026-10-06"
        return httpx.Response(
            200,
            json={
                "status_code": 20000,
                "tasks": [
                    {
                        "status_code": 20000,
                        "data": body,
                        "result": [
                            {
                                "keywords": [product.name],
                                "location_code": code,
                                "type": "trends",
                                "items": [
                                    {
                                        "type": "dataforseo_trends_graph",
                                        "keywords": [product.name],
                                        "data": [],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
        )

    provider = DataForSEOTrendProvider(
        transport=httpx.MockTransport(handler),
        clock=lambda: NOW,
        location_code=code,
        location_name=name,
    )
    result = service(repository, provider).refresh(product, Destination(country=country))
    assert result.outcome.status == "SUCCESS_EMPTY"
    assert result.telemetry.requests == {"dataforseo_trends": 1}
    assert len(requests) == 1
    assert str(requests[0].url) == DataForSEOTrendProvider.endpoint


def saved_market(repository, product):
    from src.research.market_intelligence import MarketIntelligenceService
    from src.research.research_service import EvidenceResearchService
    from tests.test_market_pipeline import FixturePages, FixtureWeb

    market = MarketIntelligenceRepository(repository.repository)
    service = MarketIntelligenceService(
        market, page_provider=FixturePages(), demand_provider=FixtureDemand(utc_now)
    )
    web = EvidenceResearchService(repository.repository, api_key="fixture", provider=FixtureWeb())
    service.research_product(product, web)
    report = market.get_report(product.id)
    from src.research.providers.retail_prices import MarketPriceObservation, summarize_prices

    report.price_observations = [
        MarketPriceObservation(
            product_name=product.name,
            retailer=f"shop{index}",
            price=20 + index,
            currency="USD",
            observed_at=report.page_verifications[index].accessed_at,
            url=source.url,
            source_id=source.id,
            availability="InStock",
            match_outcome="MATCH",
        )
        for index, source in enumerate(report.web_evidence.sources)
    ]
    report.price_summaries = summarize_prices(report.price_observations)
    market.save_report(report)
    for source, page in zip(report.web_evidence.sources, report.page_verifications):
        claims = list(
            dict.fromkeys(
                f.claim for f in report.web_evidence.findings if source.id in f.source_ids
            )
        ) or [source.what_claim_it_supports]
        claim_hash = hashlib.sha256(json.dumps(claims).encode()).hexdigest()
        market.save_cache(
            f"page-v3:{product_fingerprint(product)}:{source.id}:{claim_hash}",
            {
                "verification": page.model_dump(mode="json"),
                "prices": [
                    p.model_dump(mode="json")
                    for p in report.price_observations
                    if p.source_id == source.id
                ],
            },
            page.accessed_at,
        )
    return market, report


@pytest.mark.parametrize("fetched", [True, False])
def test_overlay_invalidates_retained_retail_after_empty_or_failed_fetch_without_v3_rewrite(
    repository, product, fetched
):
    from src.supply.demand import current_market_overlay

    market, report = saved_market(repository, product)
    before = market.get_report(product.id).model_dump_json()
    page = report.page_verifications[0].model_copy(deep=True)
    page.fetched = fetched
    page.accessed_at += timedelta(seconds=1)
    source = report.web_evidence.sources[0]
    claims = list(
        dict.fromkeys(f.claim for f in report.web_evidence.findings if source.id in f.source_ids)
    )
    claim_hash = hashlib.sha256(json.dumps(claims).encode()).hexdigest()
    market.save_cache(
        f"page-v3:{product_fingerprint(product)}:{source.id}:{claim_hash}",
        {"verification": page.model_dump(mode="json"), "prices": []},
        page.accessed_at,
    )
    overlay = current_market_overlay(product, repository, Destination())
    assert source.id not in {p.source_id for p in overlay.price_observations}
    assert overlay.price_summaries[0].count == 2
    assert market.get_report(product.id).model_dump_json() == before


def test_demand_overlay_failure_is_not_eligible_while_v3_history_is_unchanged(repository, product):
    from src.supply.demand import current_market_overlay

    market, _ = saved_market(repository, product)
    before = market.get_report(product.id).model_dump_json()
    provider = FixtureDemand(utc_now)
    demand = service(repository, provider, utc_now)
    demand.refresh(product, Destination(), force=True)
    provider.status = "failed"
    demand.refresh(product, Destination(), force=True)
    overlay = current_market_overlay(product, repository, Destination())
    assert overlay.demand.status == "failed"
    assert overlay.trend.classification == "INSUFFICIENT_DATA"
    assert overlay.score.dimensions["Numeric trend"] == 0
    assert market.get_report(product.id).model_dump_json() == before


def test_current_read_rechecks_staleness_without_requests_or_timestamp_changes(repository, product):
    clock = [NOW]
    provider = FixtureDemand(lambda: clock[0])
    demand = service(repository, provider, lambda: clock[0])
    demand.refresh(product, Destination())
    clock[0] += timedelta(days=8)
    stale = demand.get_current(product, Destination())
    assert not stale.current_eligible
    assert stale.demand.collected_at == NOW
    assert provider.request_count == 1
