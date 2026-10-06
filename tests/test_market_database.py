import sqlite3

from src.database.database import ProductRepository
from src.research.telemetry import RunTelemetry


def test_v3_extension_is_explicit_additive_and_preserves_v2_bytes(tmp_path, result):
    from src.database.market_repository import MarketIntelligenceRepository

    path = tmp_path / "v2.db"
    legacy = ProductRepository(path)
    legacy.save(result)
    with sqlite3.connect(path) as conn:
        before = conn.execute("SELECT payload FROM saved_products").fetchone()[0]
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    extension = MarketIntelligenceRepository(legacy, backup_dir=tmp_path / "backups")
    assert extension.get_report(result.product.id) is None
    extension.enable()
    extension.enable()
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        assert conn.execute("SELECT payload FROM saved_products").fetchone()[0] == before
    assert ProductRepository(path).list_saved() == [result]
    backups = list((tmp_path / "backups").glob("*.db"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2


def test_cache_and_latest_run_survive_restart_without_losing_failed_attempt(tmp_path):
    from src.database.market_repository import MarketIntelligenceRepository
    from src.research.telemetry import ProviderAttempt

    legacy = ProductRepository(tmp_path / "cache.db")
    extension = MarketIntelligenceRepository(legacy, backup_dir=tmp_path / "backups")
    first = RunTelemetry(openai_model_requests=2, web_search_calls=1)
    extension.save_run("product", first)
    extension.save_cache("page:a", {"status": "SOURCE_BLOCKED"}, first.started_at)
    failed = RunTelemetry(
        stages=[
            ProviderAttempt(
                stage="demand",
                provider="DataForSEO Trends",
                status="UNAVAILABLE",
                notice="Measured demand data unavailable",
            )
        ]
    )
    extension.save_run("product", failed)
    reopened = MarketIntelligenceRepository(ProductRepository(legacy.path))
    assert reopened.latest_run("product").run_id == failed.run_id
    assert reopened.get_cache("page:a").payload == {"status": "SOURCE_BLOCKED"}
    with sqlite3.connect(legacy.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM provider_attempts").fetchone()[0] == 2


def test_future_database_version_is_rejected_without_downgrade(tmp_path):
    import pytest

    from src.database.database import DataStoreError

    path = tmp_path / "future.db"
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version=4")
    with pytest.raises(DataStoreError):
        ProductRepository(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 4


def test_completed_run_cannot_be_replaced_with_different_counts(tmp_path):
    import pytest

    from src.database.database import DataStoreError
    from src.database.market_repository import MarketIntelligenceRepository

    repo = MarketIntelligenceRepository(
        ProductRepository(tmp_path / "immutable.db"), backup_dir=tmp_path / "backups"
    )
    run = RunTelemetry(openai_model_requests=2)
    repo.save_run("product", run)
    repo.save_run("product", run)
    changed = run.model_copy(update={"openai_model_requests": 99})
    with pytest.raises(DataStoreError):
        repo.save_run("product", changed)
    assert repo.latest_run("product").openai_model_requests == 2


def test_component_identity_excludes_collection_time_and_report_roundtrips(tmp_path, product):
    from datetime import timedelta

    from src.database.market_repository import MarketIntelligenceRepository
    from src.research.market_models import MarketIntelligenceReport
    from src.research.market_scoring import score_market_report
    from src.research.providers.base import product_fingerprint
    from src.research.providers.demand_trend import DemandObservation, DemandResult
    from src.research.providers.retail_prices import MarketPriceObservation
    from src.research.trends import TrendResult
    from src.services.market_economics import MarketEconomicsInputs, calculate_market_economics
    from tests.research_fixtures import report_fixture

    web = report_fixture()
    now = web.researched_at
    observation = DemandObservation(
        metric_name="popularity",
        provider="fixture",
        query=product.name,
        value=54,
        unit="relative_popularity_index",
        period_start=now.date() - timedelta(days=8),
        period_end=now.date() - timedelta(days=2),
        collected_at=now,
        source_url="https://provider.com/data",
        location="US",
        series_id="same-series",
    )
    demand = DemandResult(
        provider="fixture",
        query=product.name,
        location="US",
        status="completed",
        observations=[observation],
    )
    price = MarketPriceObservation(
        product_name=product.name,
        retailer="fixture",
        price=12,
        currency="USD",
        observed_at=now,
        url=web.sources[0].url,
        source_id=web.sources[0].id,
        match_outcome="MATCH",
        availability="InStock",
    )
    econ_inputs = MarketEconomicsInputs()
    econ = calculate_market_economics(econ_inputs)
    trend = TrendResult()
    report = MarketIntelligenceReport(
        product_id=product.id,
        product_name=product.name,
        input_fingerprint=product_fingerprint(product),
        web_evidence=web,
        demand=demand,
        trend=trend,
        price_observations=[price],
        economics_inputs=econ_inputs,
        economics_result=econ,
        score=score_market_report(web, [], demand, trend, [], econ),
    )
    repository = MarketIntelligenceRepository(
        ProductRepository(tmp_path / "observations.db"), backup_dir=tmp_path / "backups"
    )
    repository.save_report(report)
    later = report.model_copy(deep=True)
    later.demand.observations[0].collected_at += timedelta(seconds=1)
    later.price_observations[0].observed_at += timedelta(seconds=1)
    from decimal import Decimal

    later.price_observations[0].price = Decimal("13")
    repository.save_report(later)
    restored = MarketIntelligenceRepository(ProductRepository(repository.path)).get_report(
        product.id
    )
    assert restored.price_observations[0].price == 13
    with sqlite3.connect(repository.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM demand_observations").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM market_price_observations").fetchone()[0] == 1
