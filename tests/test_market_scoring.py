from datetime import timedelta
from types import SimpleNamespace

from src.research.models import utc_now
from src.services.market_economics import MarketEconomicsInputs, calculate_market_economics
from tests.research_fixtures import report_fixture


def inputs():
    return MarketEconomicsInputs(
        unit_product_cost=10,
        international_shipping_per_unit=5,
        import_duty_per_unit=0,
        customs_fee_per_unit=0,
        packaging_per_unit=0,
        handling_per_unit=0,
        other_variable_cost_per_unit=0,
        selling_price=40,
        payment_fee_percent=3,
        payment_fixed_fee=0.3,
        return_rate_percent=8,
        estimated_loss_per_return=12,
        estimated_ad_cost_per_order=8,
    )


def supported_pages(web, category="NEWS_EDITORIAL", date=None):
    return [
        SimpleNamespace(
            source_id=s.id,
            publisher=f"publisher{i}.com",
            category=category,
            published_at=date or utc_now(),
            updated_at=None,
            accessed_at=utc_now(),
            claims=[
                SimpleNamespace(claim=f.claim, status="VERIFIED_ON_PAGE")
                for f in web.findings
                if s.id in f.source_ids
            ],
        )
        for i, s in enumerate(web.sources)
    ]


def calculate(web, pages, measured=False, stale_prices=False, known_economics=True):
    from src.research.market_scoring import score_market_report

    now = utc_now()
    demand = SimpleNamespace(
        status="completed" if measured else "unavailable",
        observations=[SimpleNamespace(collected_at=now)] if measured else [],
    )
    trend = SimpleNamespace(classification="GROWING" if measured else "INSUFFICIENT_DATA")
    price_date = now - timedelta(days=20) if stale_prices else now
    prices = [SimpleNamespace(count=3, minimum=10, observed_at=price_date)]
    econ = calculate_market_economics(inputs() if known_economics else MarketEconomicsInputs())
    return score_market_report(web, pages, demand, trend, prices, econ, now=now)


def test_seller_claims_stay_low_and_do_not_become_independent_demand():
    web = report_fixture()
    score = calculate(web, supported_pages(web, "SELLER"), measured=True)
    assert score.confidence == "low"
    assert score.dimensions["Demand evidence"] == 0
    assert score.recommendation == "INSUFFICIENT EVIDENCE"
    assert score.final_score < 75


def test_independent_page_support_and_measured_coverage_improve_confidence():
    web = report_fixture()
    score = calculate(web, supported_pages(web), measured=True)
    assert score.confidence == "high"
    assert score.dimensions["Numeric trend"] == 7
    assert score.dimensions["Return-adjusted profitability"] == 7.27
    assert round(sum(score.weights.values()), 8) == 1
    assert score.final_score == round(
        sum(score.contributions.values()) * score.confidence_factor, 1
    )
    assert score.version == "market-v3"
    assert score.raw_score == 64.675
    assert score.final_score == 64.7


def test_missing_measured_data_prevents_high_and_dates_are_not_access_dates():
    web = report_fixture()
    pages = supported_pages(web)
    score = calculate(web, pages)
    assert score.confidence != "high"
    assert score.dimensions["Numeric trend"] == 0
    for page in pages:
        page.published_at = None
    assert calculate(web, pages, measured=True).confidence == "low"


def test_stale_publication_and_incomplete_economics_reduce_confidence():
    web = report_fixture()
    pages = supported_pages(web, date=utc_now() - timedelta(days=500))
    assert calculate(web, pages, measured=True).confidence == "low"
    fresh = supported_pages(web)
    assert calculate(web, fresh, measured=True, stale_prices=True).confidence != "high"
    no_costs = calculate(web, fresh, measured=True, known_economics=False)
    assert no_costs.recommendation == "INSUFFICIENT EVIDENCE"
    assert no_costs.dimensions["Return-adjusted profitability"] == 0


def test_partial_page_support_cannot_satisfy_verified_demand():
    web = report_fixture()
    pages = supported_pages(web)
    for page in pages:
        for claim in page.claims:
            claim.status = "PARTIALLY_SUPPORTED"
    score = calculate(web, pages, measured=True)
    assert score.confidence == "low"
    assert score.recommendation == "INSUFFICIENT EVIDENCE"


def test_stale_retained_page_support_prevents_high_even_with_fresh_metrics():
    web = report_fixture()
    pages = supported_pages(web)
    for page in pages:
        page.accessed_at -= timedelta(days=40)
    score = calculate(web, pages, measured=True)
    assert score.confidence != "high"
    assert any("page" in reason.lower() for reason in score.missing)
