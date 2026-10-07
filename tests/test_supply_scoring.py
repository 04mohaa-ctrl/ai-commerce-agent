from datetime import timedelta
from types import SimpleNamespace

import pytest

from src.supply.economics import FinancialSnapshot
from src.supply.scoring import score_opportunity, score_supply
from tests.test_supply_economics import NOW, complete_inputs, selection, updated_selection


def finance(**changes):
    return FinancialSnapshot(inputs=complete_inputs(**changes), updated_at=NOW)


def market():
    from tests.research_fixtures import report_fixture
    from tests.test_market_scoring import calculate, supported_pages

    web = report_fixture()
    pages = supported_pages(web)
    for page in pages:
        page.accessed_at = NOW
        page.published_at = NOW
        page.fetched = True
    web.researched_at = NOW
    score = calculate(web, pages, measured=True)
    score.confidence = "high"
    return SimpleNamespace(
        web_evidence=web,
        page_verifications=pages,
        score=score,
        demand=SimpleNamespace(
            provider="fixture",
            query="Pet Hair Remover",
            location="United States (2840)",
            status="completed",
            observations=[
                SimpleNamespace(
                    collected_at=NOW, series_id="series1", period_end=NOW.date() - timedelta(days=1)
                )
            ],
        ),
        trend=SimpleNamespace(classification="GROWING"),
        price_summaries=[SimpleNamespace(count=3, minimum=10, currency="USD", observed_at=[NOW])],
        telemetry=SimpleNamespace(stages=[]),
    )


def test_supply_fixed_weights_unknown_null_and_coverage_threshold():
    from src.supply.models import Destination

    result = score_supply(None, Destination(quantity=2), finance(), [], now=NOW)
    assert result.coverage == 15
    assert result.final_score is None and result.recommendation == "INSUFFICIENT EVIDENCE"
    assert result.dimensions["Product/variant match"].raw_score is None
    assert result.dimensions["Observed stock"].raw_score is None
    assert sum(d.weight for d in result.dimensions.values()) == pytest.approx(1)
    assert result.dimensions["Observed stock"].contribution == 0
    assert "missing" in result.dimensions["Observed stock"].reason.lower()


def test_complete_supply_and_configured_delivery_threshold():
    from src.supply.models import Destination

    chosen = selection()
    result = score_supply(chosen, Destination(quantity=2), finance(), [], now=NOW)
    assert result.raw_total == 100 and result.coverage == 100
    assert any(r.code == "SINGLE_PROVIDER" for r in result.risks)
    slow = score_supply(
        chosen, Destination(quantity=2, max_delivery_days=5), finance(), [], now=NOW
    )
    assert slow.dimensions["Delivery-time suitability"].raw_score == 3
    assert any(r.code == "SLOW_DELIVERY" for r in slow.risks)


@pytest.mark.parametrize("status", ["FAILED", "SUCCESS_EMPTY", "UNAVAILABLE", "RATE_LIMITED"])
def test_failed_or_empty_current_component_never_reuses_historical_stock_as_fresh(status):
    from src.supply.models import Destination

    stages = [
        {
            "component": "stock",
            "provider": "cj",
            "status": status,
            "variant_id": "v1",
            "observed_at": NOW.isoformat(),
        }
    ]
    result = score_supply(selection(), Destination(quantity=2), finance(), stages, now=NOW)
    assert result.dimensions["Observed stock"].raw_score is None
    assert result.confidence != "high"
    assert result.recommendation == "INSUFFICIENT EVIDENCE"


def test_unrelated_failed_variant_does_not_downgrade_selected_observation():
    from src.supply.models import Destination

    stages = [
        {"component": "stock", "provider": "cj", "status": "FAILED", "variant_id": "unrelated"}
    ]
    assert (
        score_supply(selection(), Destination(quantity=2), finance(), stages, now=NOW).raw_total
        == 100
    )


def test_observed_zero_is_distinct_from_unknown_and_has_evidence_id():
    from src.supply.models import Destination

    chosen = selection()
    chosen = updated_selection(chosen, "stock", quantity=0)
    result = score_supply(chosen, Destination(quantity=2), finance(), [], now=NOW)
    dim = result.dimensions["Observed stock"]
    assert dim.raw_score == 0 and chosen.offer.stock.id in dim.evidence_ids
    assert result.recommendation == "WEAK CANDIDATE"
    chosen = updated_selection(chosen, "stock", quantity=None)
    unknown = score_supply(chosen, Destination(quantity=2), finance(), [], now=NOW)
    assert unknown.dimensions["Observed stock"].raw_score is None
    assert unknown.recommendation == "INSUFFICIENT EVIDENCE"


def test_market_v4_weights_raw_dimensions_single_confidence_and_no_v3_mutation():
    from src.supply.models import Destination

    original = market()
    original.score.final_score = 1
    before = original.score.model_dump_json()
    result = score_opportunity(
        original, selection(), Destination(quantity=2), finance(), [], now=NOW
    )
    assert result.version == "market-v4"
    assert [d.weight for d in result.dimensions.values()] == [
        0.18,
        0.12,
        0.12,
        0.25,
        0.08,
        0.10,
        0.15,
    ]
    assert result.final_score == round(result.raw_total * result.confidence_factor, 1)
    assert result.dimensions["Supply feasibility"].raw_score == 10
    assert result.final_score > 1
    assert original.score.model_dump_json() == before


def test_high_market_without_selected_supply_never_strong():
    from src.supply.models import Destination

    result = score_opportunity(market(), None, Destination(quantity=2), finance(), [], now=NOW)
    assert result.confidence != "high"
    assert result.recommendation == "INSUFFICIENT EVIDENCE"
    assert result.dimensions["Supply feasibility"].raw_score is None


def test_cheap_supply_without_demand_or_complete_finances_is_insufficient():
    from src.supply.models import Destination

    absent = market()
    absent.web_evidence.demand_evidence = []
    result = score_opportunity(
        absent, selection(), Destination(quantity=2), finance(unit_product_cost=0), [], now=NOW
    )
    assert result.dimensions["Demand evidence"].raw_score is None
    assert result.recommendation == "INSUFFICIENT EVIDENCE"
    incomplete = score_opportunity(
        market(),
        selection(),
        Destination(quantity=2),
        finance(import_duty_per_unit=None),
        [],
        now=NOW,
    )
    assert incomplete.dimensions["Return-adjusted profitability"].raw_score is None
    assert incomplete.recommendation == "INSUFFICIENT EVIDENCE"


def test_stale_measurement_and_pending_shipping_cannot_support_high():
    from src.supply.models import Destination

    evidence = market()
    evidence.demand.observations[0].collected_at = NOW - timedelta(days=8)
    stages = [{"component": "shipping", "provider": "cj", "status": "UNAVAILABLE", "pending": True}]
    result = score_opportunity(
        evidence, selection(), Destination(quantity=2), finance(), stages, now=NOW
    )
    assert result.dimensions["Numeric trend"].raw_score is None
    assert result.confidence != "high" and result.recommendation == "INSUFFICIENT EVIDENCE"


def test_current_demand_failure_overrides_old_success():
    from src.supply.models import Destination

    evidence = market()
    evidence.telemetry.stages = [{"stage": "demand", "status": "SUCCESS"}]
    result = score_opportunity(
        evidence,
        selection(),
        Destination(quantity=2),
        finance(),
        [{"component": "demand", "status": "FAILED"}],
        now=NOW,
    )
    assert result.dimensions["Numeric trend"].raw_score is None
    assert result.confidence != "high"


@pytest.mark.parametrize("missing", ["retail", "publication", "partial"])
def test_retained_high_confidence_requires_current_evidence_gates(missing):
    from src.supply.models import Destination

    evidence = market()
    evidence.price_summaries = [
        SimpleNamespace(count=3, minimum=10, currency="USD", observed_at=[NOW])
    ]
    stages = []
    if missing == "retail":
        evidence.price_summaries = []
    if missing == "publication":
        for page in evidence.page_verifications:
            page.published_at = NOW - timedelta(days=400)
            page.updated_at = None
    if missing == "partial":
        stages = [{"component": "shipping", "status": "SUCCESS", "partial": True}]
    result = score_opportunity(
        evidence, selection(), Destination(quantity=2), finance(), stages, now=NOW
    )
    assert result.confidence != "high"


def test_observation_without_selected_binding_is_historical():
    from src.supply.economics import apply_supplier_cost, calculate_financial
    from src.supply.models import Destination

    snapshot = apply_supplier_cost(finance(), selection(), Destination(quantity=2), now=NOW)
    result = calculate_financial(snapshot, now=NOW)
    assert not result.current and result.economics is None


def test_fully_current_evidence_can_support_high_without_v3_mutation():
    from src.supply.models import Destination

    result = score_opportunity(
        market(), selection(), Destination(quantity=2), finance(), [], now=NOW
    )
    assert result.confidence == "high"
    assert result.confidence_factor == 1


def test_changed_destination_blocks_selected_match_score():
    from src.supply.models import Destination

    result = score_supply(
        selection(), Destination(country="SE", quantity=2), finance(), [], now=NOW
    )
    assert result.dimensions["Product/variant match"].raw_score <= 3
    assert result.recommendation == "INSUFFICIENT EVIDENCE"
