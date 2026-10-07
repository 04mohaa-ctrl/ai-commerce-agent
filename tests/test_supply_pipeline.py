import pytest

from src.database.database import ProductRepository
from src.database.supply_repository import SupplyRepository
from src.supply.models import (
    ActionTelemetry,
    Destination,
    ProviderOutcome,
    ShippingQuote,
    StockObservation,
    SupplierProductCandidate,
    SupplierSelection,
    SupplierVariant,
)
from src.supply.service import SupplierIntelligenceService


@pytest.mark.parametrize(
    "budget,provider_reply,status,source,dispatch_count",
    [
        (1, "unused", "BUDGET_EXHAUSTED", "LOCAL_REQUEST_BUDGET", 1),
        (12, "429", "RATE_LIMITED", "PROVIDER_RATE_LIMIT", 2),
        (12, "quota", "RATE_LIMITED", "PROVIDER_QUOTA_LIMIT", 2),
    ],
)
def test_real_cj_limit_origin_survives_cache_report_and_action_restart(
    tmp_path, monkeypatch, product, budget, provider_reply, status, source, dispatch_count
):
    import httpx

    from src.supply.cj_provider import CJDropShippingProvider
    from tests.test_cj_transport import Clock, auth, make_transport

    clock = Clock()
    dispatched = []

    def handler(request):
        dispatched.append(request.url.path)
        if "authentication" in request.url.path:
            return httpx.Response(200, json=auth(clock))
        if provider_reply == "429":
            return httpx.Response(429, headers={"Retry-After": "100"})
        assert provider_reply == "quota"
        return httpx.Response(200, json={"code": 1600201, "result": False})

    transport, _ = make_transport(monkeypatch, handler, clock=clock)
    provider = CJDropShippingProvider(transport=transport)
    provider.reset_action = lambda run, **kwargs: transport.reset_action(run, max_requests=budget)
    repo = SupplyRepository(
        ProductRepository(tmp_path / "limits.db"), backup_dir=tmp_path / "backup"
    )
    report = SupplierIntelligenceService(repo, provider).research(product, Destination())
    assert len(dispatched) == dispatch_count
    assert report.telemetry.requests == ({"auth": 1} if budget == 1 else {"auth": 1, "search": 1})
    assert report.stages[0]["status"] == status
    assert report.stages[0]["limit_source"] == source
    if provider_reply == "429":
        assert report.stages[0]["retry_blocked_by"] == "LOCAL_TIME_BUDGET"
    restarted = SupplyRepository(ProductRepository(repo.path))
    assert restarted.get_report(product.id).telemetry.stages[0]["limit_source"] == source
    assert restarted.get_latest_action(product.id).stages[0]["status"] == status


class FixtureSupplier:
    name = "fixture"
    configured = True
    cache_context = "fixture-account"

    def __init__(self, product):
        self.calls = []
        self.product = product
        self.search_status = "SUCCESS"
        self.stock_status = "SUCCESS"
        self.shipping_status = "SUCCESS"
        self.telemetry = ActionTelemetry()

    def reset_action(self, telemetry, **kwargs):
        self.telemetry = telemetry

    def outcome(self, component, records, status="SUCCESS"):
        self.calls.append(component)
        self.telemetry.requests[component] = self.telemetry.requests.get(component, 0) + 1
        return ProviderOutcome(status=status, records=records if status == "SUCCESS" else [])

    def search(self, query, **kwargs):
        assert query == self.product.name
        candidate = SupplierProductCandidate(provider="fixture", product_id="pid1", name=query)
        return self.outcome("search", [candidate.model_dump(mode="json")], self.search_status)

    def details(self, pid):
        assert pid == "pid1"
        candidate = SupplierProductCandidate(
            provider="fixture", product_id=pid, name=self.product.name
        )
        return self.outcome("details", [candidate.model_dump(mode="json")])

    def variants(self, pid):
        variant = SupplierVariant(
            provider="fixture",
            product_id=pid,
            variant_id="vid1",
            name=self.product.name,
            unit_price=5,
            currency="USD",
        )
        return self.outcome("variants", [variant.model_dump(mode="json")])

    def stock(self, vid, *, product_id):
        stock = StockObservation(
            provider="fixture",
            product_id=product_id,
            variant_id=vid,
            warehouse_id="area1",
            storage_id="sub1",
            country="CN",
            quantity=20,
        )
        return self.outcome("stock", [stock.model_dump(mode="json")], self.stock_status)

    def shipping(self, variant, stock, destination):
        quote = ShippingQuote(
            provider="fixture",
            product_id=variant.product_id,
            variant_id=variant.variant_id,
            variant_snapshot=variant.id,
            warehouse_id=stock.warehouse_id,
            storage_id=stock.storage_id,
            origin=stock.country,
            destination=destination,
            quantity=destination.quantity,
            method="Fixture parcel",
            total_cost=12,
            currency="USD",
            delivery_min_days=5,
            delivery_max_days=10,
        )
        return self.outcome("shipping", [quote.model_dump(mode="json")], self.shipping_status)


def setup(tmp_path, product):
    repo = ProductRepository(tmp_path / "flow.db")
    supply = SupplyRepository(repo, backup_dir=tmp_path / "backups")
    provider = FixtureSupplier(product)
    return supply, provider, SupplierIntelligenceService(supply, provider=provider)


def test_research_cache_and_reads_make_no_new_calls(tmp_path, product):
    repo, provider, service = setup(tmp_path, product)
    report = service.research(product, Destination())
    assert len(report.offers) == 1
    assert report.offers[0].stock.quantity == 20
    original = report.offers[0].variant.observed_at
    calls = list(provider.calls)
    report = service.research(product, Destination())
    assert provider.calls == calls
    assert report.offers[0].variant.observed_at == original
    assert len(report.telemetry.cache_hits) == 4
    assert repo.get_report(product.id) is not None
    assert provider.calls == calls


def test_successful_empty_clears_current_offers_but_preserves_selection(tmp_path, product):
    repo, provider, service = setup(tmp_path, product)
    first = service.research(product, Destination())
    selection = SupplierSelection(offer=first.offers[0])
    repo.save_selection(product.id, selection)
    provider.search_status = "SUCCESS_EMPTY"
    report = service.research(product, Destination(), force=True)
    assert report.offers == []
    assert repo.get_selection(product.id).id == selection.id
    assert repo.get_report(product.id).offers == []


def test_failed_refresh_retains_history_and_marks_failure(tmp_path, product):
    repo, provider, service = setup(tmp_path, product)
    first = service.research(product, Destination())
    provider.search_status = "FAILED"
    report = service.research(product, Destination(), force=True)
    assert report.offers == first.offers
    assert any(s["status"] == "FAILED" for s in report.stages)
    assert any(s.get("retained") for s in report.stages)


def test_action_uuid_is_consumed_once_and_demo_never_dispatches(tmp_path, product):
    repo, provider, service = setup(tmp_path, product)
    service.research(product, Destination(), action_id="one-action")
    count = len(provider.calls)
    service.research(product, Destination(), force=True, action_id="one-action")
    assert len(provider.calls) == count
    service.research(product, Destination(), force=True, demo=True)
    assert len(provider.calls) == count


def test_stock_empty_does_not_infer_available_from_catalog(tmp_path, product):
    _, provider, service = setup(tmp_path, product)
    service.research(product, Destination())
    provider.stock_status = "SUCCESS_EMPTY"
    report = service.research(product, Destination(), force=True)
    assert len(report.offers) == 1
    assert report.offers[0].stock is None


def test_shipping_refresh_requires_explicit_adoption_and_preserves_financial(tmp_path, product):
    from src.supply.economics import FinancialSnapshot, apply_shipping_cost

    repo, provider, service = setup(tmp_path, product)
    report = service.research(product, Destination(quantity=3))
    selected = SupplierSelection(offer=report.offers[0])
    repo.save_selection(product.id, selected)
    refreshed = service.refresh_shipping(product, Destination(quantity=3))
    assert repo.get_selection(product.id).id == selected.id
    assert refreshed.offers[0].quote.total_cost == 12
    assert any(s["status"] == "UNAVAILABLE" for s in service.current_stages(product))
    adopted = SupplierSelection(offer=refreshed.offers[0])
    repo.save_selection(product.id, adopted)
    snapshot = apply_shipping_cost(
        FinancialSnapshot(),
        adopted,
        Destination(quantity=3),
        stages=service.current_stages(product),
    )
    repo.save_financial(product.id, snapshot)
    assert snapshot.inputs.international_shipping_per_unit == 4
    provider.shipping_status = "SUCCESS_EMPTY"
    cleared = service.refresh_shipping(product, Destination(quantity=3))
    assert cleared.offers[0].quote is None
    assert repo.get_selection(product.id).id == adopted.id
    assert repo.get_financial(product.id).model_dump() == snapshot.model_dump()


def test_shipping_does_not_dispatch_for_new_incompatible_customer_market(tmp_path, product):
    from src.supply.models import SupplierMatch

    electrical = product.model_copy(update={"name": "Electric heated lunch box"})
    repo, provider, service = setup(tmp_path, electrical)
    report = service.research(electrical, Destination())
    base = report.offers[0]
    variant = base.variant.model_copy(
        update={
            "name": "Electric heated lunch box 110V US plug",
            "attributes": {"voltage": "110V", "plug": "US"},
        }
    )
    offer = base.model_copy(update={"variant": variant, "match": SupplierMatch(outcome="MATCH")})
    report.offers = [offer]
    repo.save_report(report)
    repo.save_selection(electrical.id, SupplierSelection(offer=offer))
    calls = list(provider.calls)
    service.refresh_shipping(electrical, Destination(country="SE"))
    assert provider.calls == calls


def test_empty_shipping_refresh_clears_all_methods_for_selected_warehouse(tmp_path, product):
    repo, provider, service = setup(tmp_path, product)
    first = service.research(product, Destination())
    repo.save_selection(product.id, SupplierSelection(offer=first.offers[0]))
    single_shipping = provider.shipping

    def multiple_methods(*args):
        result = single_shipping(*args)
        if result.records:
            quote = ShippingQuote.model_validate(result.records[0])
            result.records.append(
                quote.model_copy(update={"method": "Fixture express"}).model_dump(mode="json")
            )
        return result

    provider.shipping = multiple_methods
    quoted = service.refresh_shipping(product, Destination())
    assert len(quoted.offers) == 2
    provider.shipping_status = "SUCCESS_EMPTY"
    cleared = service.refresh_shipping(product, Destination())
    assert len(cleared.offers) == 1
    assert all(o.quote is None for o in cleared.offers)


def test_rejected_variants_do_not_hide_compatible_variant_within_enrichment_budget(
    tmp_path, product
):
    product = product.model_copy(update={"name": "Electric heated lunch box", "description": ""})
    _, provider, service = setup(tmp_path, product)

    def variants(pid):
        records = []
        for vid, voltage, plug in [
            ("eu1", "220V", "EU"),
            ("eu2", "230V", "EU"),
            ("us", "110V", "US"),
        ]:
            v = SupplierVariant(
                provider="fixture",
                product_id=pid,
                variant_id=vid,
                name=product.name,
                attributes={"voltage": voltage, "plug": plug},
                unit_price=5,
                currency="USD",
            )
            records.append(v.model_dump(mode="json"))
        return provider.outcome("variants", records)

    provider.variants = variants
    report = service.research(product, Destination(country="US"))
    assert any(o.variant.variant_id == "us" and o.stock for o in report.offers)
    assert provider.calls.count("stock") == 1


def test_changed_product_inputs_make_prior_selection_historical_and_block_shipping(
    tmp_path, product
):
    from src.supply.economics import supplier_cost_issue, utc_now

    repo, provider, service = setup(tmp_path, product)
    report = service.research(product, Destination())
    repo.save_selection(product.id, SupplierSelection(offer=report.offers[0]))
    changed = product.model_copy(update={"description": "Capacity: 1L; pack of 2"})
    assert changed.id == product.id
    from src.supply.economics import FinancialSnapshot
    from src.supply.scoring import score_supply

    score = score_supply(
        repo.get_selection(product.id),
        Destination(),
        FinancialSnapshot(),
        service.current_stages(changed),
    )
    assert score.dimensions["Product/variant match"].raw_score <= 3
    assert score.recommendation == "INSUFFICIENT EVIDENCE"
    assert (
        supplier_cost_issue(
            repo.get_selection(product.id),
            "USD",
            utc_now(),
            service.current_stages(changed),
            Destination(),
        )
        is not None
    )
    calls = list(provider.calls)
    service.refresh_shipping(changed, Destination())
    assert provider.calls == calls


def test_unrelated_catalog_rows_do_not_consume_viable_candidate_budget(tmp_path, product):
    _, provider, service = setup(tmp_path, product)

    def search(query, **kwargs):
        names = ["Wireless headphones", "USB charging cable", "Gaming keyboard", product.name]
        records = [
            SupplierProductCandidate(
                provider="fixture", product_id=f"other{i}" if i < 3 else "pid1", name=name
            ).model_dump(mode="json")
            for i, name in enumerate(names)
        ]
        return provider.outcome("search", records)

    provider.search = search
    report = service.research(product, Destination())
    assert any(o.variant.product_id == "pid1" and o.stock for o in report.offers)
    assert provider.calls == ["search", "details", "variants", "stock"]
