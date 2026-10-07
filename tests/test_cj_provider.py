"""Sanitized official CJ-shaped catalog, variant, stock and freight fixtures."""

import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from tests.test_cj_transport import Clock, auth, make_transport


def provider_for(monkeypatch, data, *, clock=None):
    from src.supply.cj_provider import CJDropShippingProvider

    clock = clock or Clock()
    requests = []

    def handler(request):
        requests.append(request)
        if "authentication" in request.url.path:
            return httpx.Response(200, json=auth(clock))
        return httpx.Response(200, json={"code": 200, "result": True, "data": data})

    transport, _ = make_transport(monkeypatch, handler, clock=clock)
    return CJDropShippingProvider(transport=transport), requests


def variant():
    from src.supply.models import SupplierVariant

    return SupplierVariant(provider="cj", product_id="p", variant_id="v", name="Lunch box 110V")


def stock(**kwargs):
    from src.supply.models import StockObservation

    payload = dict(
        provider="cj",
        product_id="p",
        variant_id="v",
        warehouse_id="1",
        storage_id="warehouse-real",
        country="CN",
        quantity=20,
    )
    payload.update(kwargs)
    return StockObservation(**payload)


def test_unavailable_provider_never_dispatches_and_all_capabilities_are_typed(monkeypatch):
    from src.supply.models import Destination
    from src.supply.providers import UnavailableSupplierProvider

    provider = UnavailableSupplierProvider()
    assert not provider.configured
    results = [
        provider.search("box"),
        provider.details("p"),
        provider.variants("p"),
        provider.stock("v", product_id="p"),
        provider.shipping(variant(), stock(), Destination()),
    ]
    assert all(result.status == "UNAVAILABLE" and result.records == [] for result in results)
    assert provider.telemetry.requests == {}


def test_nested_list_v2_partial_and_deduplicated_with_safe_fields(monkeypatch):
    data = {
        "content": [
            {
                "productList": [
                    {
                        "id": "p",
                        "nameEn": "Lunch box",
                        "bigImage": "https://images.example/box.jpg",
                        "threeCategoryName": "Kitchen",
                        "apiKey": "must-never-persist",
                        "sellPrice": "3",
                    },
                    {
                        "id": "p",
                        "nameEn": "Lunch box",
                        "bigImage": "https://images.example/box.jpg",
                        "threeCategoryName": "Kitchen",
                    },
                    {"nameEn": "No ID"},
                    {"id": "q", "nameEn": "Other box", "bigImage": "http://127.0.0.1/private"},
                ]
            },
            {"productList": "malformed"},
        ]
    }
    provider, _ = provider_for(monkeypatch, data)
    result = provider.search("Lunch box")
    assert result.status == "SUCCESS" and result.partial and result.rejected == 2
    assert [item["product_id"] for item in result.records] == ["p", "q"]
    assert result.records[0]["category"] == "Kitchen"
    assert result.records[0]["source_url"] is None
    assert result.records[1]["image_url"] is None
    assert "apiKey" not in json.dumps(result.model_dump(mode="json"))
    assert "unit_price" not in result.records[0]


@pytest.mark.parametrize(
    "data,status,rejected",
    [
        ({"content": []}, "SUCCESS_EMPTY", 0),
        ({"content": [{"productList": []}]}, "SUCCESS_EMPTY", 0),
        ({"content": [{"productList": [{"nameEn": "No ID"}]}]}, "FAILED", 1),
        ({"content": "malformed"}, "FAILED", 1),
        (None, "FAILED", 1),
        ([], "FAILED", 1),
    ],
)
def test_search_empty_is_distinct_from_malformed(monkeypatch, data, status, rejected):
    provider, _ = provider_for(monkeypatch, data)
    result = provider.search("box")
    assert result.status == status and result.records == [] and result.rejected == rejected


def test_details_is_exact_identity_and_does_not_call_variants(monkeypatch):
    provider, requests = provider_for(
        monkeypatch,
        {
            "pid": "p",
            "productNameEn": "Lunch box",
            "variants": [{"vid": "v"}],
            "productImage": "https://images.example/box.jpg",
        },
    )
    result = provider.details("p")
    assert result.status == "SUCCESS"
    assert result.records[0]["product_id"] == "p"
    assert len(requests) == 2
    assert provider.telemetry.requests == {"auth": 1, "details": 1}


def test_details_wrong_product_identity_is_failed(monkeypatch):
    provider, _ = provider_for(monkeypatch, {"pid": "other", "productNameEn": "Wrong"})
    result = provider.details("p")
    assert result.status == "FAILED" and result.records == [] and result.rejected == 1


def test_variant_units_native_usd_and_missing_fields_stay_unknown(monkeypatch):
    provider, _ = provider_for(
        monkeypatch,
        [
            {
                "pid": "p",
                "vid": "v",
                "variantNameEn": "110V US Plug Red",
                "variantSku": "SKU-red",
                "variantKey": "Red-US Plug-110V",
                "variantLength": 300,
                "variantWidth": 200,
                "variantHeight": 100,
                "variantWeight": "1580",
                "variantSellPrice": "58.09",
                "cookie": "must-never-persist",
            },
            {"pid": "p", "vid": "unknown", "variantNameEn": "Unknown cost"},
        ],
    )
    result = provider.variants("p")
    assert result.status == "SUCCESS" and not result.partial
    priced, unknown = result.records
    assert priced["unit_price"] == "58.09" and priced["currency"] == "USD"
    assert priced["dimensions_mm"] == ["300", "200", "100"]
    assert priced["weight_g"] == "1580"
    assert unknown["unit_price"] is None and unknown["weight_g"] is None
    assert unknown["dimensions_mm"] is None
    assert "cookie" not in json.dumps(result.model_dump(mode="json"))


@pytest.mark.parametrize(
    "bad",
    [
        {"pid": "other", "vid": "v", "variantNameEn": "Wrong identity"},
        {"pid": "p", "vid": "v", "variantNameEn": "Bad price", "variantSellPrice": "NaN"},
        {"pid": "p", "vid": "v", "variantNameEn": "Bad weight", "variantWeight": -1},
    ],
)
def test_rejected_variant_rows_cannot_become_empty_success(monkeypatch, bad):
    provider, _ = provider_for(monkeypatch, [bad])
    result = provider.variants("p")
    assert result.status == "FAILED" and result.rejected == 1


def test_stock_has_separate_cj_and_factory_quantities_and_real_subwarehouse(monkeypatch):
    provider, _ = provider_for(
        monkeypatch,
        [
            {
                "vid": "v",
                "areaId": "1",
                "countryCode": "CN",
                "totalInventoryNum": 23,
                "cjInventoryNum": 3,
                "factoryInventoryNum": 20,
                "stock": [{"stockId": "warehouse-real", "inventory": 3, "factoryInventory": 20}],
            },
            {
                "vid": "v",
                "areaId": "2",
                "countryCode": "US",
                "totalInventoryNum": 0,
                "cjInventoryNum": 0,
                "factoryInventoryNum": 0,
            },
            {"vid": "v", "areaId": "3", "countryCode": "GB"},
        ],
    )
    result = provider.stock("v", product_id="p")
    assert result.status == "SUCCESS"
    first, zero, unknown = result.records
    assert first["storage_id"] == "warehouse-real" and first["warehouse_id"] == "1"
    assert (first["quantity"], first["cj_quantity"], first["factory_quantity"]) == (23, 3, 20)
    assert zero["quantity"] == 0 and zero["storage_id"] is None
    assert unknown["quantity"] is None and unknown["storage_id"] is None


def test_stock_rejects_wrong_variant_without_guessing_pid(monkeypatch):
    provider, requests = provider_for(monkeypatch, [{"vid": "other", "areaId": "1"}])
    assert provider.stock("v").status == "UNSUPPORTED"
    assert requests == []
    result = provider.stock("v", product_id="p")
    assert result.status == "FAILED" and result.rejected == 1


def test_stock_unknown_factory_does_not_claim_derived_total(monkeypatch):
    provider, _ = provider_for(
        monkeypatch,
        [
            {
                "vid": "v",
                "areaId": "1",
                "countryCode": "CN",
                "totalInventoryNum": 100,
                "stock": [{"stockId": "real", "inventory": 3}],
            }
        ],
    )
    record = provider.stock("v", product_id="p").records[0]
    assert record["quantity"] is None
    assert record["cj_quantity"] == 3 and record["factory_quantity"] is None


@pytest.mark.parametrize(
    "data,status,rejected",
    [
        ([], "SUCCESS_EMPTY", 0),
        ([{"vid": "v", "totalInventoryNum": -1}], "FAILED", 1),
        ([{"vid": "v", "totalInventoryNum": "20"}], "FAILED", 1),
        ([{"vid": "v", "stock": {"stockId": "bad"}}], "FAILED", 1),
    ],
)
def test_stock_empty_and_invalid_are_distinct(monkeypatch, data, status, rejected):
    provider, _ = provider_for(monkeypatch, data)
    result = provider.stock("v", product_id="p")
    assert result.status == status and result.rejected == rejected


@pytest.mark.parametrize(
    "change",
    [{"storage_id": None}, {"country": None}, {"variant_id": "other"}, {"product_id": "other"}],
)
def test_unbound_freight_is_unsupported_with_zero_dispatches(monkeypatch, change):
    from src.supply.models import Destination

    provider, requests = provider_for(monkeypatch, [])
    result = provider.shipping(variant(), stock(**change), Destination())
    assert result.status == "UNSUPPORTED" and requests == []


def test_freight_exact_one_variant_quantity_and_storage_preserves_quote_total(monkeypatch):
    from src.supply.models import Destination, ShippingQuote

    provider, requests = provider_for(
        monkeypatch,
        [
            {
                "logisticName": "USPS+",
                "logisticPrice": "12.00",
                "logisticPriceCn": "90.00",
                "logisticAging": "2-5",
                "taxesFee": "1.25",
                "clearanceOperationFee": "0.50",
                "totalPostageFee": "13.75",
            },
            {"logisticName": "Slow service", "logisticPrice": "8.00"},
        ],
    )
    destination = Destination(country="US", quantity=3)
    result = provider.shipping(variant(), stock(), destination)
    assert result.status == "SUCCESS"
    body = json.loads(requests[-1].content)
    assert body == {
        "startCountryCode": "CN",
        "endCountryCode": "US",
        "products": [{"quantity": 3, "vid": "v"}],
        "storageIdList": ["warehouse-real"],
    }
    quote = ShippingQuote.model_validate(result.records[0])
    assert quote.total_cost == Decimal("12.00") and quote.currency == "USD"
    assert quote.total_postage_fee == Decimal("13.75")
    assert quote.taxes_fee == Decimal("1.25")
    assert (quote.delivery_min_days, quote.delivery_max_days, quote.tracking) == (2, 5, None)
    assert quote.destination == destination
    assert quote.observed_at == datetime(2026, 10, 7, 0, 0, 1, tzinfo=UTC)
    assert result.records[1]["delivery_min_days"] is None
    assert result.records[1]["delivery_max_days"] is None
    assert result.records[1]["tracking"] is None


def test_freight_missing_price_delivery_and_tracking_remain_unknown(monkeypatch):
    from src.supply.models import Destination

    provider, _ = provider_for(
        monkeypatch,
        [{"logisticName": "Unknown", "logisticAging": "estimated soon", "isTracking": True}],
    )
    result = provider.shipping(variant(), stock(), Destination())
    record = result.records[0]
    assert record["total_cost"] is None
    assert record["delivery_min_days"] is None and record["tracking"] is None


@pytest.mark.parametrize(
    "data,status,rejected",
    [
        ([], "SUCCESS_EMPTY", 0),
        ([{"logisticName": "Bad", "logisticPrice": "NaN"}], "FAILED", 1),
        ([{"logisticPrice": "1"}], "FAILED", 1),
        ([{"logisticName": "Valid", "logisticPrice": "1"}, {}], "SUCCESS", 1),
    ],
)
def test_freight_empty_partial_and_malformed_are_distinct(monkeypatch, data, status, rejected):
    from src.supply.models import Destination

    provider, _ = provider_for(monkeypatch, data)
    result = provider.shipping(variant(), stock(), Destination())
    assert result.status == status and result.rejected == rejected
    assert result.partial == (status == "SUCCESS" and rejected > 0)


def test_unconfigured_cj_stock_and_freight_remain_unavailable(monkeypatch):
    from src.supply.cj_provider import CJDropShippingProvider
    from src.supply.cj_transport import CJResearchTransport
    from src.supply.models import Destination

    monkeypatch.delenv("CJ_API_KEY", raising=False)
    provider = CJDropShippingProvider(
        transport=CJResearchTransport(
            http_transport=httpx.MockTransport(lambda _: pytest.fail("must not dispatch"))
        )
    )
    assert provider.stock("v").status == "UNAVAILABLE"
    assert (
        provider.shipping(variant(), stock(storage_id=None), Destination()).status == "UNAVAILABLE"
    )
    assert provider.telemetry.requests == {}


def test_freight_binds_exact_requested_variant_observation(monkeypatch):
    from src.supply.models import Destination, ShippingQuote

    provider, _ = provider_for(monkeypatch, [{"logisticName": "USPS+", "logisticPrice": "12.00"}])
    requested = variant()
    result = provider.shipping(requested, stock(), Destination())
    assert result.status == "SUCCESS"
    assert result.records[0].get("variant_snapshot") == requested.id
    quote = ShippingQuote.model_validate(result.records[0])
    assert quote.variant_snapshot == requested.id
