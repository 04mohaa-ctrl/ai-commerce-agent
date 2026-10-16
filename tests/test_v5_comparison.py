"""V5 comparisons reuse V4 arithmetic and retain separate query series."""

from datetime import timedelta

import pytest

from src.agents.product_research_agent import ProductResearchAgent
from src.database.database import ProductRepository
from src.database.supply_repository import SupplyRepository
from src.schemas.product import Product
from src.supply.models import Destination


def saved(repo, count=3):
    rows = [
        ProductResearchAgent(force_demo=True).analyze(
            Product(name=name, category="Synthetic acceptance")
        )
        for name in ["Laptop stand", "Pet brush", "Lunch box", "Travel bag", "Desk lamp"][:count]
    ]
    for row in rows:
        repo.save(row)
        SupplyRepository(repo).save_settings(row.product.id, Destination(country="SE"))
    return rows


def test_group_validation_and_restart(tmp_path):
    from src.discovery.comparison import ComparisonGroup, save_group
    from src.discovery.repository import DiscoveryRepository

    repo = ProductRepository(tmp_path / "groups.db")
    rows = saved(repo)
    ids = [r.product.id for r in rows]
    group = ComparisonGroup(
        name="Swedish shortlist",
        product_ids=ids,
        decision="Investigate",
        notes="Verify product fit before a sample.",
    )
    save_group(repo, group)
    restarted = DiscoveryRepository(ProductRepository(repo.path)).list_groups()
    assert restarted[0]["notes"] == group.notes
    with pytest.raises(ValueError):
        ComparisonGroup(name="Duplicates", product_ids=[ids[0]] * 3)
    with pytest.raises(ValueError):
        save_group(repo, ComparisonGroup(name="Missing", product_ids=ids[:2] + ["missing"]))


@pytest.mark.parametrize(
    "changed,expected",
    [
        ({"country": "US"}, "geography"),
        ({"quantity": 2}, "quantity"),
    ],
)
def test_comparability_and_unknowns(tmp_path, changed, expected):
    from src.discovery.comparison import comparison_workspace

    repo = ProductRepository(tmp_path / "compare.db")
    rows = saved(repo)
    extension = SupplyRepository(repo)
    extension.save_settings(
        rows[0].product.id, Destination(country="SE").model_copy(update=changed)
    )
    doc = comparison_workspace(rows, repo)
    assert not doc["comparability"]["directly_comparable"]
    assert any(expected in reason for reason in doc["comparability"]["issues"])
    assert doc["schema"] == "ai-commerce-v5-comparison-1"
    assert (
        doc["products"][0]["financial"]["calculation"]["economics"]["estimated_net_profit"] is None
    )
    assert doc["products"][0]["next_actions"]
    assert doc["prioritization"]["winner"] is None


def test_tax_currency_fx_comparability(tmp_path):
    from src.discovery.comparison import comparison_workspace
    from src.supply.economics import FinancialSnapshot
    from src.supply.financial_scenario import TaxAssumptions

    repo = ProductRepository(tmp_path / "tax.db")
    rows = saved(repo)
    for index, row in enumerate(rows):
        SupplyRepository(repo).save_financial(
            row.product.id,
            FinancialSnapshot(
                currency="EUR" if index == 0 else "USD",
                tax_assumptions=TaxAssumptions(
                    price_basis="NO_VAT" if index == 0 else "VAT_INCLUSIVE", sales_vat_percent=25
                ),
            ),
        )
    issues = comparison_workspace(rows, repo)["comparability"]["issues"]
    assert any("currency" in x for x in issues)
    assert any("tax" in x for x in issues)


def test_comparison_rows_use_currency_neutral_labels(tmp_path):
    from src.discovery.comparison import comparison_workspace, workspace_rows
    from src.supply.economics import FinancialSnapshot

    repo = ProductRepository(tmp_path / "currency-labels.db")
    rows = saved(repo)
    for row in rows:
        SupplyRepository(repo).save_financial(row.product.id, FinancialSnapshot(currency="EUR"))
    displayed = workspace_rows(comparison_workspace(rows, repo))
    assert all(row["Scenario currency"] == "EUR" for row in displayed)
    assert not any("USD" in key for row in displayed for key in row)


def test_five_complete_manual_scenarios_are_comparable_without_inventing_a_winner(tmp_path):
    from src.discovery.comparison import comparison_workspace
    from src.services.market_economics import MarketEconomicsInputs
    from src.supply.economics import FinancialSnapshot
    from src.supply.financial_scenario import TaxAssumptions

    repo = ProductRepository(tmp_path / "five.db")
    rows = saved(repo, count=5)
    for row in rows:
        values = {field: 0 for field in MarketEconomicsInputs.model_fields}
        values.update(
            unit_product_cost=5,
            international_shipping_per_unit=9,
            selling_price=25,
            payment_fee_percent=3,
            payment_fixed_fee=0.3,
            estimated_ad_cost_per_order=2,
        )
        SupplyRepository(repo).save_financial(
            row.product.id,
            FinancialSnapshot(
                inputs=MarketEconomicsInputs(**values),
                tax_assumptions=TaxAssumptions(price_basis="NO_VAT", import_vat_per_unit=0),
            ),
        )
    before = repo.path.read_bytes()
    document = comparison_workspace(rows, repo)
    assert len(document["products"]) == 5
    assert document["comparability"]["directly_comparable"]
    assert all(
        item["financial"]["calculation"]["economics"]["estimated_net_profit"] == 7.95
        for item in document["products"]
    )
    assert document["prioritization"]["winner"] is None
    assert repo.path.read_bytes() == before


def test_separate_queries_batch_budget_cache_and_export(tmp_path, product):
    from src.discovery.comparison import comparison_workspace
    from src.discovery.queries import QueryPlan, QueryTerm, run_queries, save_query_plan
    from src.supply.demand import DemandIntelligenceService
    from tests.test_supply_demand import NOW, FixtureDemand

    repo = ProductRepository(tmp_path / "queries.db")
    row = ProductResearchAgent(force_demo=True).analyze(product)
    repo.save(row)
    destination = Destination()
    terms = [
        QueryTerm(query=product.name, language="en"),
        QueryTerm(query="pälsborttagare", language="sv"),
    ]
    plan = QueryPlan(country="US", terms=terms)
    save_query_plan(repo, product, plan)
    provider = FixtureDemand()
    demand = DemandIntelligenceService(repo, provider, clock=lambda: NOW)
    outcomes = run_queries(repo, product, destination, plan, demand=demand, max_requests=1)
    assert [o["status"] for o in outcomes] == ["SUCCESS", "NOT_STARTED"]
    assert demand.get_current(product, destination, query="pälsborttagare") is None
    outcomes = run_queries(repo, product, destination, plan, demand=demand)
    assert provider.request_count == 2  # first query cache reused
    assert all(o["status"] == "SUCCESS" for o in outcomes)
    doc = comparison_workspace([row], repo, now=NOW)
    assert len(doc["products"][0]["query_evidence"]) == 2
    queries = {s["query"] for s in doc["products"][0]["query_evidence"]}
    assert queries == {product.name, "pälsborttagare"}
    assert "not absolute" in doc["semantics"]["query_series"]
    stale = comparison_workspace([row], repo, now=NOW + timedelta(days=8))
    assert not any(s["current_eligible"] for s in stale["products"][0]["query_evidence"])


def test_query_plan_requires_review_and_matching_geography(tmp_path, product):
    from src.discovery.queries import QueryPlan, QueryTerm, run_queries

    with pytest.raises(ValueError):
        QueryPlan(country="SE", terms=[QueryTerm(query="x", language="en")] * 6)
    repo = ProductRepository(tmp_path / "q.db")
    plan = QueryPlan(country="SE", terms=[QueryTerm(query="stand", language="en")])
    with pytest.raises(ValueError, match="market"):
        run_queries(repo, product, Destination(country="US"), plan)


def test_query_batch_partial_failure_deadline_and_case_identity(tmp_path, product):
    from src.discovery.queries import QueryPlan, QueryTerm, run_queries
    from src.supply.demand import DemandIntelligenceService
    from tests.test_supply_demand import NOW, FixtureDemand

    repo = ProductRepository(tmp_path / "partial.db")

    class Partial(FixtureDemand):
        def collect(self, requested):
            self.status = "failed" if requested.name == "Pet Brush" else "completed"
            return super().collect(requested)

    provider = Partial()
    demand = DemandIntelligenceService(repo, provider, clock=lambda: NOW)
    plan = QueryPlan(
        country="US",
        terms=[
            QueryTerm(query="pet brush", language="en"),
            QueryTerm(query="Pet Brush", language="en"),
        ],
    )
    rows = run_queries(repo, product, Destination(), plan, demand=demand)
    assert [r["status"] for r in rows] == ["SUCCESS", "FAILED"]
    assert demand.get_current(product, Destination(), query="pet brush").current_eligible
    assert demand.get_current(product, Destination(), query="Pet Brush").outcome.status == "FAILED"
    now = iter([0, 119, 119])
    before = provider.request_count
    stopped = run_queries(
        repo, product, Destination(), plan, demand=demand, monotonic=lambda: next(now)
    )
    assert all(r["status"] == "NOT_STARTED" for r in stopped)
    assert provider.request_count == before
