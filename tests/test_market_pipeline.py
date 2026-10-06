from src.database.database import ProductRepository
from src.research.models import utc_now
from src.research.research_service import EvidenceResearchService
from tests.research_fixtures import report_fixture


class FixtureWeb:
    telemetry = None
    price_loader = None

    def __init__(self):
        self.calls = 0

    def research(self, product, progress=None):
        self.calls += 1
        return report_fixture()


class FixturePages:
    request_count = 0
    source_fetch_count = 0

    def verify(self, source, claims):
        from src.research.providers.page_verification import VerifiedPage
        from src.research.verification import ClaimVerification, PageVerification

        self.source_fetch_count += 1
        self.request_count += 2
        return VerifiedPage(
            verification=PageVerification(
                source_id=source.id,
                canonical_url=source.url,
                publisher=source.url.split("/")[2],
                accessed_at=utc_now(),
                fetched=True,
                published_at=utc_now(),
                date_status="KNOWN",
                category="NEWS_EDITORIAL",
                claims=[ClaimVerification(claim=c, status="VERIFIED_ON_PAGE") for c in claims],
            ),
            html="<html><p>fixture</p></html>",
        )


def setup(tmp_path):
    from src.database.market_repository import MarketIntelligenceRepository
    from src.research.market_intelligence import MarketIntelligenceService

    repo = ProductRepository(tmp_path / "pipeline.db")
    extension = MarketIntelligenceRepository(repo, backup_dir=tmp_path / "backups")
    web, pages = FixtureWeb(), FixturePages()
    service = EvidenceResearchService(repo, api_key="fixture-secret", provider=web)
    market = MarketIntelligenceService(extension, page_provider=pages)
    return repo, extension, web, pages, service, market


def test_one_shared_flow_persists_partial_components_and_actual_run_counts(tmp_path, product):
    repo, ext, web, pages, evidence, market = setup(tmp_path)
    result = market.research_product(product, evidence, force=True)
    report = ext.get_report(product.id)
    assert result.status == "completed" and repo.get_research(product.id).sources
    assert len(report.page_verifications) == 3
    assert report.demand.status == "unavailable"
    assert report.demand.notice == "Measured demand data unavailable"
    assert report.telemetry.page_fetch_count == 3
    assert report.telemetry.page_request_count == 6
    assert report.telemetry.demand_requests == 0
    assert report.telemetry.openai_model_requests == 0  # fixture caused no real HTTP requests
    assert ext.latest_run(product.id).run_id == report.telemetry.run_id


def test_explicit_research_reuses_components_but_force_refresh_requests_again(tmp_path, product):
    _, ext, web, pages, evidence, market = setup(tmp_path)
    market.research_product(product, evidence)
    first = ext.get_report(product.id)
    market.research_product(product, evidence)
    latest = ext.latest_run(product.id)
    assert web.calls == 1 and pages.source_fetch_count == 3
    assert latest.page_request_count == 0 and latest.openai_model_requests == 0
    assert "web" in latest.cache_hits and "demand" in latest.cache_hits
    assert (
        ext.get_report(product.id).page_verifications[0].accessed_at
        == first.page_verifications[0].accessed_at
    )
    market.research_product(product, evidence, force=True)
    assert web.calls == 2 and pages.source_fetch_count == 6


def test_failed_demand_does_not_erase_pages_and_failure_is_sanitized(tmp_path, product):
    _, ext, _, _, evidence, market = setup(tmp_path)

    class DemandFailure:
        name = "fixture-demand"
        request_count = 0

        def collect(self, product):
            self.request_count += 1
            raise RuntimeError("fixture-secret internal provider problem")

    market.demand_provider = DemandFailure()
    market.research_product(product, evidence)
    report = ext.get_report(product.id)
    assert len(report.page_verifications) == 3
    assert report.web_evidence.sources
    assert report.demand.status == "failed"
    assert report.telemetry.demand_requests == 1
    assert "fixture-secret" not in report.model_dump_json()


def test_demo_and_keyless_do_not_fetch_and_retain_previous_reports(tmp_path, product):
    _, ext, web, pages, evidence, market = setup(tmp_path)
    market.research_product(product, evidence)
    previous = ext.get_report(product.id)
    evidence.force_demo = True
    market.research_product(product, evidence, force=True)
    assert web.calls == 1 and pages.source_fetch_count == 3
    assert ext.get_report(product.id) == previous
    assert all(s.status == "DISABLED" for s in ext.latest_run(product.id).stages)
    evidence.force_demo = False
    evidence.api_key = ""
    market.research_product(product, evidence, force=True)
    assert pages.source_fetch_count == 3


def test_changed_fingerprint_does_not_reuse_previous_component_cache(tmp_path, product):
    _, ext, web, pages, evidence, market = setup(tmp_path)
    market.research_product(product, evidence)
    changed = product.model_copy(update={"description": "Different researched variant"})
    market.research_product(changed, evidence)
    assert web.calls == 2 and pages.source_fetch_count == 6
    from src.research.providers.base import product_fingerprint

    assert ext.get_report(product.id).input_fingerprint == product_fingerprint(changed)


def test_web_refresh_can_preserve_independent_page_and_demand_caches(tmp_path, product):
    _, ext, web, pages, evidence, market = setup(tmp_path)
    market.research_product(product, evidence)
    market.research_product(product, evidence, refresh_web=True)
    assert web.calls == 2
    assert pages.source_fetch_count == 3
    assert "demand" in ext.latest_run(product.id).cache_hits


def test_failed_web_attempt_is_cached_without_automatic_paid_retry(tmp_path, product):
    from src.research.providers.base import ResearchProviderError

    _, _, web, _, evidence, market = setup(tmp_path)

    def fail(*args, **kwargs):
        web.calls += 1
        raise ResearchProviderError("External research unavailable.")

    web.research = fail
    market.research_product(product, evidence)
    market.research_product(product, evidence)
    assert web.calls == 1


def test_recalculation_rechecks_numeric_trend_freshness_without_requests(tmp_path, product):
    from datetime import timedelta

    from src.research.providers.demand_trend import DemandObservation, DemandResult
    from src.research.trends import TrendResult

    _, ext, web, pages, evidence, market = setup(tmp_path)
    market.research_product(product, evidence)
    report = ext.get_report(product.id)
    now = utc_now()
    observations = [
        DemandObservation(
            metric_name="popularity",
            provider="fixture",
            query=product.name,
            value=50 + i,
            unit="relative_popularity_index",
            period_start=now.date() - timedelta(days=82 - i * 7),
            period_end=now.date() - timedelta(days=76 - i * 7),
            collected_at=now,
            source_url="https://provider.com/series",
            location="US",
            series_id="one",
        )
        for i in range(6)
    ]
    report.demand = DemandResult(
        provider="fixture",
        query=product.name,
        location="US",
        status="completed",
        observations=observations,
    )
    report.trend = TrendResult(
        classification="GROWING",
        prior_average=50,
        recent_average=60,
        change_percent=20,
        observation_count=6,
    )
    ext.save_report(report)
    recalculated = market.recalculate(product)
    assert recalculated.trend.classification == "INSUFFICIENT_DATA"
    assert web.calls == 1 and pages.source_fetch_count == 3


def test_canonical_listing_urls_keep_original_citation_identity_and_survive_failure(
    tmp_path, product
):
    import json

    _, ext, _, _, evidence, market = setup(tmp_path)

    class CanonicalPages(FixturePages):
        def verify(self, source, claims):
            page = super().verify(source, claims)
            page.verification.canonical_url = source.url + "/canonical"
            page.html = (
                '<script type="application/ld+json">'
                + json.dumps(
                    {
                        "@type": "Product",
                        "name": product.name,
                        "offers": {
                            "price": 12,
                            "priceCurrency": "USD",
                            "availability": "https://schema.org/InStock",
                        },
                    }
                )
                + "</script>"
            )
            return page

    market.page_provider = CanonicalPages()
    market.research_product(product, evidence)
    report = ext.get_report(product.id)
    assert len(report.price_observations) == 3
    assert {p.source_id for p in report.price_observations} <= {
        s.id for s in report.web_evidence.sources
    }

    class FailedPages:
        request_count = 0
        source_fetch_count = 0

        def verify(self, source, claims):
            raise RuntimeError("Page unavailable")

    market.page_provider = FailedPages()
    market.research_product(product, evidence, force=True)
    assert len(ext.get_report(product.id).price_observations) == 3


def test_each_page_fetch_receives_remaining_shared_time_budget(tmp_path, product, monkeypatch):
    from types import SimpleNamespace

    import src.research.market_intelligence as module

    _, _, _, _, evidence, market = setup(tmp_path)

    class BudgetPages(FixturePages):
        def __init__(self):
            self.fetcher = SimpleNamespace(total_timeout=40)
            self.budgets = []

        def verify(self, source, claims):
            self.budgets.append(self.fetcher.total_timeout)
            return super().verify(source, claims)

    pages = BudgetPages()
    market.page_provider = pages
    ticks = iter([0.0, 0.0, 50.0, 59.0])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(ticks))
    market.research_product(product, evidence)
    assert pages.budgets == [40, 10, 1]
    assert pages.fetcher.total_timeout == 40


def test_partial_web_refresh_reports_retained_completed_snapshot_honestly(tmp_path, product):
    _, ext, web, _, evidence, market = setup(tmp_path)
    market.research_product(product, evidence)
    original = ext.get_report(product.id).web_evidence.researched_at

    def partial(*args, **kwargs):
        report = report_fixture()
        report.status = "insufficient"
        report.notice = "Only partial new evidence was available."
        return report

    web.research = partial
    market.research_product(product, evidence, force=True)
    report = ext.get_report(product.id)
    web_stage = next(s for s in report.telemetry.stages if s.stage == "web")
    assert report.web_evidence.researched_at == original
    assert web_stage.status == "PARTIAL"
    assert web_stage.retained is True


def test_successful_refresh_supersedes_old_failed_attempt_cache(tmp_path, product):
    from src.research.providers.base import ResearchProviderError

    _, ext, web, _, evidence, market = setup(tmp_path)

    def fail(*args, **kwargs):
        web.calls += 1
        raise ResearchProviderError("External unavailable")

    web.research = fail
    market.research_product(product, evidence)
    web.research = lambda *args, **kwargs: report_fixture()
    market.research_product(product, evidence, refresh_web=True)
    result = market.research_product(product, evidence)
    assert result.status == "completed"
    assert next(s for s in ext.latest_run(product.id).stages if s.stage == "web").status == "CACHED"


def test_manual_economics_recalculation_removes_obsolete_missing_cost_risk(tmp_path, product):
    from tests.test_market_scoring import inputs

    _, ext, web, pages, evidence, market = setup(tmp_path)
    market.research_product(product, evidence)
    assert any("economics incomplete" in flag for flag in ext.get_report(product.id).risk_flags)
    ext.save_economics(product.id, inputs())
    report = market.recalculate(product)
    assert report.economics_result.estimated_net_profit == 14.54
    assert not any("economics incomplete" in flag for flag in report.risk_flags)
    assert web.calls == 1 and pages.source_fetch_count == 3
