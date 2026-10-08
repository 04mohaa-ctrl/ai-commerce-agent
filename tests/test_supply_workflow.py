"""Full offline workflow; freight is a contract fixture, never a live Swedish quote."""

import json
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from src.agents.product_research_agent import ProductResearchAgent
from src.database.database import ProductRepository
from src.database.supply_repository import SupplyRepository
from src.research.providers.base import product_fingerprint
from src.schemas.product import Product
from src.supply.models import Destination, SupplierOffer, SupplyIntelligenceReport
from tests.test_supply_requirements import button

APP = Path(__file__).resolve().parents[1] / "app.py"


def seed(path):
    data = json.loads((Path(__file__).parent / "fixtures/v4_laptop_stand.json").read_text())
    product = Product.model_validate(data["product"])
    offers = [SupplierOffer.model_validate(o) for o in data["offers"]]
    repo = ProductRepository(path)
    repo.save(ProductResearchAgent(force_demo=True).analyze(product))
    ext = SupplyRepository(repo, path.parent / "backup")
    dest = Destination(country="SE")
    ext.save_settings(product.id, dest)
    ext.save_report(
        SupplyIntelligenceReport(
            product_id=product.id,
            input_fingerprint=product_fingerprint(product),
            destination=dest,
            offers=offers,
            stages=data["stages"],
            researched_at=data["researched_at"],
        )
    )
    return product, ext, offers


def test_refreshed_candidate_observation_blocks_historical_shipping(tmp_path, monkeypatch):
    from src.supply.models import SupplierRequirements, SupplierSelection
    from src.supply.service import SupplierIntelligenceService
    from tests.test_supply_pipeline import FixtureSupplier

    product, ext, offers = seed(tmp_path / "candidate.db")
    monkeypatch.setattr(
        "src.supply.service.utc_now", lambda: offers[0].variant.observed_at + timedelta(minutes=5)
    )
    ext.save_requirements(product.id, SupplierRequirements(color="black"))
    service = SupplierIntelligenceService(ext, FixtureSupplier(product))
    report = service.recheck_saved(product, Destination(country="SE"))
    ext.save_selection(product.id, SupplierSelection(offer=report.offers[0]))
    report.offers[0] = report.offers[0].model_copy(
        update={
            "candidate": offers[0].candidate.model_copy(
                update={"observed_at": offers[0].candidate.observed_at + timedelta(seconds=1)}
            )
        }
    )
    ext.save_report(report)
    assert service.shipping_request_issue(product, Destination(country="SE")) is not None
    refreshed = service.refresh_shipping(product, Destination(country="SE"))
    assert refreshed.stages[-1]["shipping_state"] == "BLOCKED"
    assert service.provider.calls == []


def test_captured_sparse_demand_failure_remains_historical(tmp_path):
    from src.supply.demand import DemandIntelligenceService, DemandSnapshot
    from src.supply.models import ProviderOutcome

    product, ext, _ = seed(tmp_path / "demand.db")
    data = json.loads(
        (Path(__file__).parent / "fixtures/v4_sparse_demand_snapshot.json").read_text()
    )
    snapshot = DemandSnapshot.model_validate(data)
    service = DemandIntelligenceService(ext, clock=lambda: snapshot.outcome.observed_at)
    key = service._current_key(product, Destination(country="SE"), product.name)
    ext.save_cache(
        key, ProviderOutcome(status="SUCCESS", records=[snapshot.model_dump(mode="json")])
    )
    current = service.get_current(product, Destination(country="SE"))
    assert current.outcome.status == "FAILED"
    assert current.retained and not current.current_eligible
    assert len(current.demand.observations) == 52
    assert sum(not o.missing for o in current.demand.observations) == 3
    assert current.trend.classification == "INSUFFICIENT_DATA"
    assert current.trend.change_percent is None


def test_replayed_freight_response_passes_real_adapter_with_exact_identity(tmp_path):
    from src.supply.cj_provider import CJDropShippingProvider
    from src.supply.cj_transport import CJTransportOutcome

    _, _, offers = seed(tmp_path / "adapter.db")
    offer = offers[0]
    data = json.loads(
        (Path(__file__).parent / "fixtures/v4_freight_contract_response.json").read_text()
    )

    class Transport:
        configured = True

        def request(self, operation, parameters):
            assert operation == "shipping"
            assert parameters == {
                "startCountryCode": "CN",
                "endCountryCode": "SE",
                "products": [{"quantity": 1, "vid": "1CC71DF3-9C07-43FD-9B78-074266306AD0"}],
                "storageIdList": ["{6709CCD7-0DC7-43B1-B310-17AB499E9B0A}"],
            }
            return CJTransportOutcome(status="SUCCESS", data=data["response"]["data"])

    result = CJDropShippingProvider(transport=Transport()).shipping(
        offer.variant, offer.stock, Destination(country="SE")
    )
    assert result.status == "SUCCESS"
    assert result.records[0]["total_cost"] == "12.00"
    assert result.records[0]["variant_snapshot"] == offer.variant.id
    assert result.records[0]["tracking"] is None


def test_unconfigured_freight_is_blocked_before_dispatch(tmp_path):
    from src.supply.models import SupplierRequirements, SupplierSelection
    from src.supply.service import SupplierIntelligenceService
    from tests.test_supply_pipeline import FixtureSupplier

    product, ext, _ = seed(tmp_path / "unconfigured.db")
    provider = FixtureSupplier(product)
    ext.save_requirements(product.id, SupplierRequirements(color="black"))
    service = SupplierIntelligenceService(ext, provider)
    report = service.recheck_saved(product, Destination(country="SE"))
    ext.save_selection(product.id, SupplierSelection(offer=report.offers[0]))
    provider.configured = False
    assert service.shipping_request_issue(product, Destination(country="SE")) is not None
    report = service.refresh_shipping(product, Destination(country="SE"))
    assert report.stages[-1]["shipping_state"] == "BLOCKED"
    assert provider.calls == []


def test_invalid_quote_response_is_failed_and_retains_previous_quote(tmp_path, monkeypatch):
    from src.supply.models import (
        ProviderOutcome,
        ShippingQuote,
        SupplierRequirements,
        SupplierSelection,
    )
    from src.supply.service import SupplierIntelligenceService
    from tests.test_supply_pipeline import FixtureSupplier

    product, ext, offers = seed(tmp_path / "invalid.db")
    now = offers[0].variant.observed_at + timedelta(minutes=5)
    monkeypatch.setattr("src.supply.service.utc_now", lambda: now)
    monkeypatch.setattr("src.supply.economics.utc_now", lambda: now)
    ext.save_requirements(product.id, SupplierRequirements(color="black"))
    provider = FixtureSupplier(product)
    service = SupplierIntelligenceService(ext, provider)
    report = service.recheck_saved(product, Destination(country="SE"))
    offer = report.offers[0]
    quote = ShippingQuote(
        provider="cj",
        product_id=offer.variant.product_id,
        variant_id=offer.variant.variant_id,
        variant_snapshot=offer.variant.id,
        warehouse_id=offer.stock.warehouse_id,
        storage_id=offer.stock.storage_id,
        origin="CN",
        destination=Destination(country="SE"),
        quantity=1,
        method="Prior contract parcel",
        total_cost=12,
        currency="USD",
        observed_at=now,
    )
    report.offers[0] = offer.model_copy(update={"quote": quote})
    ext.save_report(report)
    ext.save_selection(product.id, SupplierSelection(offer=report.offers[0]))
    provider.shipping = lambda *args: ProviderOutcome(
        status="SUCCESS", records=[{"invalid": "quote"}]
    )
    refreshed = service.refresh_shipping(product, Destination(country="SE"))
    assert refreshed.stages[-1]["shipping_state"] == "FAILED"
    assert any(o.quote and o.quote.id == quote.id for o in refreshed.offers)


def test_structured_requirements_quote_choice_adoption_and_restart(tmp_path, monkeypatch):
    from src.supply.models import ProviderOutcome, ShippingQuote
    from tests.test_supply_pipeline import FixtureSupplier

    product, ext, offers = seed(tmp_path / "flow.db")
    now = offers[0].variant.observed_at + timedelta(minutes=10)
    monkeypatch.setenv("DATABASE_PATH", str(ext.path))
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("CJ_API_KEY", "offline-fixture")
    monkeypatch.setattr("src.ui.supplier_intelligence.utc_now", lambda: now)
    monkeypatch.setattr("src.ui.supplier_shipping.utc_now", lambda: now)
    monkeypatch.setattr("src.supply.service.utc_now", lambda: now)
    monkeypatch.setattr("src.supply.economics.utc_now", lambda: now)
    provider = FixtureSupplier(product)

    def shipping(variant, stock, destination):
        return ProviderOutcome(
            status="SUCCESS",
            observed_at=now,
            records=[
                ShippingQuote(
                    provider=variant.provider,
                    product_id=variant.product_id,
                    variant_id=variant.variant_id,
                    variant_snapshot=variant.id,
                    warehouse_id=stock.warehouse_id,
                    storage_id=stock.storage_id,
                    origin=stock.country,
                    destination=destination,
                    quantity=destination.quantity,
                    method="Replayed contract parcel",
                    total_cost=12,
                    currency="USD",
                    delivery_min_days=2,
                    delivery_max_days=5,
                    observed_at=now,
                ).model_dump(mode="json")
            ],
        )

    provider.shipping = shipping
    monkeypatch.setattr("src.supply.service.CJDropShippingProvider", lambda: provider)
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.sidebar.radio("nav").set_value("Saved Products").run()
    colors = [t for t in app.text_input if t.label == "Required supplier color"]
    assert colors, "The saved offer workflow needs a structured color input"
    assert any("Target preference unspecified: color" in m.value for m in app.markdown)
    assert product.description == ext.repository.list_saved()[0].product.description
    # The primary form is next to the offers, scoped to this product.
    colors[-1].set_value("Black")
    button(app, "Save supplier requirements and recheck").click().run()
    assert not app.exception
    assert ext.get_requirements(product.id).color == "black"
    assert ext.repository.list_saved()[0].product.description == product.description
    selects = [b for b in app.button if b.label == "Select this offer"]
    assert [b.disabled for b in selects] == [False, True, True]
    selects[0].click().run()
    button(app, "Apply observed supplier cost").click().run()
    prior = ext.get_financial(product.id)
    assert prior.inputs.unit_product_cost == 3.1
    app.sidebar.radio("nav").set_value("Settings").run()
    app.toggle("demo_mode").set_value(False).run()
    app.sidebar.radio("nav").set_value("Saved Products").run()
    assert not button(app, "Refresh shipping").disabled
    button(app, "Refresh shipping").click().run()
    assert not app.exception
    assert ext.get_selection(product.id).offer.quote is None
    assert ext.get_financial(product.id).model_dump_json() == prior.model_dump_json()
    assert any(s.label == "Shipping method for selected variant" for s in app.selectbox), (
        ext.get_report(product.id).stages[-1]
    )
    button(app, "Select shipping quote").click().run()
    assert not app.exception
    assert ext.get_selection(product.id).offer.quote.method == "Replayed contract parcel"
    assert not button(app, "Apply observed supplier cost").disabled
    button(app, "Apply current shipping quote").click().run()
    finance = ext.get_financial(product.id)
    assert finance.inputs.unit_product_cost == 3.1
    assert finance.inputs.international_shipping_per_unit == 12
    assert finance.provenance["international_shipping_per_unit"].observation_id == (
        ext.get_selection(product.id).offer.quote.id
    )
    reopened = AppTest.from_file(str(APP), default_timeout=30).run()
    reopened.sidebar.radio("nav").set_value("Saved Products").run()
    assert not reopened.exception
    assert reopened.text_input(colors[-1].key).value == "black"
    assert reopened.number_input(f"v4_econ_{product.id}_unit_product_cost").value == 3.1
    assert (
        reopened.number_input(f"v4_econ_{product.id}_international_shipping_per_unit").value == 12
    )


@pytest.mark.parametrize(
    "failure,kind,status",
    [
        ("timeout", "TIMEOUT", None),
        ("http", "HTTP_REJECTION", 403),
        ("provider", "PROVIDER_REJECTION", None),
        ("invalid", "INVALID_RESPONSE", None),
    ],
)
def test_demand_failure_has_safe_actionable_classification(monkeypatch, failure, kind, status):
    from src.research.providers.demand_trend import DataForSEOTrendProvider

    monkeypatch.setenv("DATAFORSEO_LOGIN", "private-login")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "private-password")

    def handler(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("private-password", request=request)
        if failure == "http":
            return httpx.Response(403, text="private-password")
        if failure == "provider":
            return httpx.Response(
                200, json={"status_code": 40200, "status_message": "private-password"}
            )
        return httpx.Response(200, text="private-password")

    result = DataForSEOTrendProvider(transport=httpx.MockTransport(handler)).collect(
        Product(name="Foldable Laptop Stand", category="Office")
    )
    assert result.status == "failed"
    assert getattr(result, "failure_kind", None) == kind
    assert result.http_status == status
    assert "private-password" not in result.model_dump_json()
