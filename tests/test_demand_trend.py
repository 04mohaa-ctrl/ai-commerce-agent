import json
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from src.research.providers.demand_trend import (
    DataForSEOTrendProvider,
    DemandObservation,
    UnavailableDemandProvider,
)
from src.research.trends import calculate_trend

NOW = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)


def observation(start, value, **changes):
    data = dict(
        metric_name="keyword_popularity",
        provider="fixture",
        query="Pet Hair Remover",
        value=value,
        unit="relative_popularity_index",
        period_start=start,
        period_end=start + timedelta(days=6),
        collected_at=NOW,
        source_url="https://dataforseo.com/",
        confidence="medium",
        notes=[],
        location="United States (2840)",
        series_id="one",
        missing=value == 0,
        granularity="7 days",
    )
    data.update(changes)
    return DemandObservation(**data)


def series(prior=40, recent=60):
    start = date(2026, 4, 7)
    return [
        observation(start + timedelta(days=7 * i), prior if i < 13 else recent) for i in range(26)
    ]


def response_payload(product, body):
    return {
        "status_code": 20000,
        "tasks": [
            {
                "status_code": 20000,
                "data": body,
                "result": [
                    {
                        "keywords": [product.name],
                        "location_code": 2840,
                        "type": "web",
                        "items": [
                            {
                                "type": "dataforseo_trends_graph",
                                "keywords": [product.name],
                                "data": [
                                    {
                                        "date_from": "2026-09-21",
                                        "date_to": "2026-09-27",
                                        "values": [0],
                                    },
                                    {
                                        "date_from": "2026-09-28",
                                        "date_to": "2026-10-04",
                                        "values": [64],
                                    },
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("DATAFORSEO_LOGIN", "fixture-login")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "fixture-password")


@pytest.mark.parametrize("missing", ["DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD"])
def test_disabled_does_not_create_client_or_request(monkeypatch, product, configured, missing):
    monkeypatch.delenv(missing)
    monkeypatch.setattr(httpx, "Client", lambda **kw: pytest.fail("Disabled created client"))
    provider = DataForSEOTrendProvider(clock=lambda: NOW)
    result = provider.collect(product)
    assert result.status == "unavailable"
    assert result.notice == "Measured demand data unavailable"
    assert provider.request_count == 0
    assert not result.observations
    assert UnavailableDemandProvider().collect(product).notice == result.notice


def test_native_exact_request_preserves_raw_zero_and_normalization(product, configured):
    requests = []

    def handler(request):
        requests.append(request)
        body = json.loads(request.content)[0]
        assert str(request.url) == DataForSEOTrendProvider.endpoint
        assert request.method == "POST"
        assert body == {
            "keywords": [product.name],
            "location_code": 2840,
            "type": "web",
            "date_from": "2025-10-06",
            "date_to": "2026-10-05",
        }
        return httpx.Response(200, json=response_payload(product, body))

    provider = DataForSEOTrendProvider(transport=httpx.MockTransport(handler), clock=lambda: NOW)
    a, b = provider.collect(product), provider.collect(product)
    assert a.status == "completed" and provider.request_count == 2
    assert a.observations[0].value == 0 and a.observations[0].missing
    assert a.observations[1].value == 64 and not a.observations[1].missing
    assert a.observations[1].unit == "relative_popularity_index"
    assert a.observations[0].series_id != b.observations[0].series_id
    assert "fixture-password" not in repr(provider)


@pytest.mark.parametrize(
    "bad",
    [
        "auth",
        "redirect",
        "timeout",
        "root",
        "task",
        "query",
        "location",
        "graph",
        "date",
        "future",
        "values",
        "nan",
    ],
)
def test_provider_errors_are_sanitized_and_never_retried(product, configured, bad):
    seen = []

    def handler(request):
        seen.append(request)
        if bad == "timeout":
            raise httpx.ReadTimeout("fixture-password", request=request)
        if bad in {"auth", "redirect"}:
            return httpx.Response(
                401 if bad == "auth" else 302,
                headers={"location": "https://other.example/"},
                text="fixture-password",
            )
        data = response_payload(product, json.loads(request.content)[0])
        result = data["tasks"][0]["result"][0]
        graph = result["items"][0]
        if bad == "root":
            data["status_code"] = 40100
        if bad == "task":
            data["tasks"][0]["status_code"] = 40100
        if bad == "query":
            result["keywords"] = ["wrong query"]
        if bad == "location":
            result["location_code"] = 2826
        if bad == "graph":
            graph["type"] = "wrong"
        if bad == "date":
            graph["data"][0]["date_from"] = "not-date"
        if bad == "future":
            graph["data"][0]["date_to"] = "2026-10-07"
        if bad == "values":
            graph["data"][0]["values"] = [10, 20]
        if bad == "nan":
            graph["data"][0]["values"] = ["NaN"]
        return httpx.Response(200, json=data)

    provider = DataForSEOTrendProvider(transport=httpx.MockTransport(handler), clock=lambda: NOW)
    result = provider.collect(product)
    assert result.status == "failed" and not result.observations
    assert "fixture-password" not in result.model_dump_json()
    assert len(seen) == provider.request_count == 1


@pytest.mark.parametrize(
    "recent,classification",
    [
        (60, "STRONGLY_GROWING"),
        (46, "GROWING"),
        (40, "STABLE"),
        (34, "DECLINING"),
        (20, "STRONGLY_DECLINING"),
    ],
)
def test_numeric_trend_thresholds(recent, classification):
    result = calculate_trend(series(recent=recent), now=NOW)
    assert result.classification == classification
    assert result.prior_average == 40
    assert result.recent_average == recent
    assert result.observation_count == 26


@pytest.mark.parametrize(
    "bad",
    ["sparse", "stale", "conflict", "overlap", "region", "series", "zero", "future", "cadence"],
)
def test_insufficient_series_never_manufactures_trend(bad):
    rows = series()
    now = NOW
    if bad == "sparse":
        rows = rows[::2]
    if bad == "stale":
        now = NOW + timedelta(days=45)
    if bad == "conflict":
        rows.append(rows[0].model_copy(update={"value": 99}))
    if bad == "overlap":
        rows.append(
            rows[0].model_copy(update={"period_start": rows[0].period_start + timedelta(days=1)})
        )
    if bad == "region":
        rows[-1].location = "UK"
    if bad == "series":
        rows[-1].series_id = "separately normalized"
    if bad == "zero":
        for row in rows[:13]:
            row.value, row.missing = 0, True
    if bad == "future":
        now = NOW - timedelta(days=20)
    if bad == "cadence":
        rows[-1].period_end += timedelta(days=1)
    result = calculate_trend(rows, now=now)
    assert result.classification == "INSUFFICIENT_DATA"
    assert result.notes


def test_identical_bins_deduplicate_and_eighty_percent_coverage_is_enough():
    rows = series()
    assert calculate_trend(rows + [rows[0]], now=NOW).observation_count == 26
    rows = [row for i, row in enumerate(rows) if i not in {2, 4, 15, 17}]
    result = calculate_trend(rows, now=NOW)
    assert result.classification == "STRONGLY_GROWING"
    assert result.observation_count == 22


def test_official_native_response_uses_trends_result_type(product, configured):
    def handler(request):
        data = response_payload(product, json.loads(request.content)[0])
        data["tasks"][0]["result"][0]["type"] = "trends"
        return httpx.Response(200, json=data)

    result = DataForSEOTrendProvider(
        transport=httpx.MockTransport(handler), clock=lambda: NOW
    ).collect(product)
    assert result.status == "completed"


def test_daily_series_prefers_two_ninety_day_windows():
    rows = [
        observation(
            date(2026, 3, 1) + timedelta(days=i),
            40 if i < 129 else 60,
            period_end=date(2026, 3, 1) + timedelta(days=i),
            granularity="1 day",
        )
        for i in range(219)
    ]
    result = calculate_trend(rows, now=NOW)
    assert result.classification == "STRONGLY_GROWING"
    assert result.observation_count == 180
    assert (result.period_end - result.period_start).days + 1 == 180
