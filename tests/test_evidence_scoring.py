from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError


def make_report(*, domain_count=3, missing_trend=False):
    from src.research.models import EvidenceFinding, QualitativeDimensions, ResearchReport, Source

    sources = [
        Source(
            title=f"Source {i}",
            url=f"https://publisher{i}.com/product",
            accessed_at=datetime.now(timezone.utc),
            source_type="web",
            what_claim_it_supports="A source-linked observation.",
        )
        for i in range(domain_count)
    ]
    item = EvidenceFinding(
        claim="A source-linked observation.",
        supporting_excerpt="A source-linked observation.",
        source_ids=[source.id for source in sources],
    )
    return ResearchReport(
        product_name="Test",
        sources=sources,
        demand_evidence=[item],
        competition_evidence=[item],
        trend_evidence=[] if missing_trend else [item],
        marketing_angles=[item],
        dimensions=QualitativeDimensions(
            demand="strong", competition="weak", trend="strong", marketing="strong"
        ),
    )


def test_sources_normalize_tracking_and_have_stable_identity():
    from src.research.models import Source

    a = Source(
        title="Retail page",
        url="https://SHOP.example.com/product?sku=1&utm_source=chatgpt#top",
        accessed_at=datetime.now(timezone.utc),
        source_type="web",
        what_claim_it_supports="Claim",
    )
    b = a.model_copy(update={"title": "Different title"})
    from src.research.models import canonical_url

    assert a.url == "https://shop.example.com/product?sku=1"
    assert canonical_url("https://shop.example.com/product?utm_campaign=x&sku=1") == a.url
    assert a.id == b.id


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "file:///secret",
        "http://localhost:8080",
        "https://user:password@example.com/a",
        "http://127.0.0.1/a",
    ],
)
def test_source_links_reject_unsafe_urls(url):
    from src.research.models import Source

    with pytest.raises(ValidationError):
        Source(
            title="Unsafe",
            url=url,
            accessed_at=datetime.now(timezone.utc),
            source_type="web",
            what_claim_it_supports="Claim",
        )


def test_confidence_requires_coverage_and_multiple_publishers():
    from src.research.scoring import confidence_for

    assert confidence_for(make_report(domain_count=1)) == "low"
    assert confidence_for(make_report(missing_trend=True)) == "low"
    assert confidence_for(make_report()) == "medium"
    old = make_report()
    old.researched_at = datetime.now(timezone.utc) - timedelta(days=8)
    assert confidence_for(old) == "low"


def test_evidence_score_uses_net_economics_and_confidence_adjustment():
    from src.research.scoring import calculate_evidence_score
    from src.services.economics import EconomicsInputs

    score = calculate_evidence_score(
        make_report(),
        EconomicsInputs(
            product_cost=10,
            selling_price=40,
            shipping_cost=5,
            payment_fee_percent=3,
            estimated_ad_cost_per_order=8,
        ),
    )
    # Demand 22.5 + net margin 9.875 + trend 18 + inverse competition 10.5 + marketing 13.5.
    assert score.unadjusted_total == pytest.approx(74.375)
    assert score.total == 63.2
    assert score.confidence_level == "medium"
    assert score.confidence_factor == 0.85
    assert score.components["Profit margin"] == 9.875
    assert score.profit_potential == 3.95


def test_no_evidence_cannot_get_a_high_confidence_or_estimate_driven_score():
    from src.research.models import QualitativeDimensions, ResearchReport
    from src.research.scoring import calculate_evidence_score
    from src.services.economics import EconomicsInputs

    report = ResearchReport(
        product_name="Test",
        dimensions=QualitativeDimensions(
            demand="strong", competition="weak", trend="strong", marketing="strong"
        ),
        confidence_level="high",
    )
    score = calculate_evidence_score(report, EconomicsInputs(product_cost=0, selling_price=40))
    assert score.total == 0
    assert score.confidence_level == "low"
    assert score.profit_potential == 0


def test_unresolvable_finding_source_is_rejected():
    from src.research.models import EvidenceFinding, ResearchReport

    with pytest.raises(ValidationError):
        ResearchReport(
            product_name="Test",
            demand_evidence=[
                EvidenceFinding(
                    claim="Claim", supporting_excerpt="Claim", source_ids=["invented-source-id"]
                )
            ],
        )


def test_effective_analysis_timestamp_matches_research_without_mutating_saved_snapshot(result):
    from src.research.providers.base import product_fingerprint
    from src.research.scoring import decorate_result
    from src.services.economics import EconomicsInputs

    report = make_report()
    report.product_name = result.product.name
    report.input_fingerprint = product_fingerprint(result.product)
    report.researched_at = result.analyzed_at + timedelta(hours=1)
    original_timestamp = result.analyzed_at
    effective = decorate_result(result, report, EconomicsInputs(product_cost=4, selling_price=20))
    assert effective.analyzed_at == report.researched_at
    assert result.analyzed_at == original_timestamp
