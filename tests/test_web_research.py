import json

import httpx
import pytest
from openai import OpenAI

from tests.research_fixtures import QUOTES, URLS, extraction_payload, web_response
from tests.test_agent import response_body


def provider_for(handler):
    from src.research.providers.web_research import WebResearchProvider

    client = OpenAI(
        api_key="test-secret",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    return WebResearchProvider(
        api_key="test-secret", client=client, price_loader=lambda *args: []
    ), client


def test_real_sdk_retrieval_parse_and_tool_citations_are_preserved(product):
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        payload = (
            web_response(duplicate=True)
            if "tools" in body
            else response_body(json.dumps(extraction_payload()))
        )
        return httpx.Response(200, json=payload)

    provider, client = provider_for(handler)
    with client:
        report = provider.research(product)
    assert report.status == "completed"
    assert report.mode == "web"
    assert len(report.sources) == 3
    assert report.demand_evidence[0].supporting_excerpt == QUOTES[0]
    assert report.demand_evidence[0].source_ids == [report.sources[0].id]
    assert report.confidence_level == "medium"
    assert report.observed_price_range is None
    assert seen[0]["tools"][0]["type"] == "web_search"
    assert seen[0]["tool_choice"] == "required"
    assert "web_search_call.action.sources" in seen[0]["include"]
    assert seen[0]["store"] is False and seen[1]["store"] is False
    assert seen[1]["text"]["format"]["type"] == "json_schema"
    assert len(seen) == 2


def test_absent_citations_mean_insufficient_evidence_not_generated_sources(product):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=web_response(citations=False))

    provider, client = provider_for(handler)
    with client:
        report = provider.research(product)
    assert report.status == "insufficient"
    assert report.research_summary == "Insufficient evidence"
    assert report.sources == [] and report.demand_evidence == []
    assert report.confidence_level == "low"
    assert len(calls) == 1


@pytest.mark.parametrize("bad", ["invented_url", "invented_excerpt"])
def test_untraceable_evidence_is_dropped_instead_of_presented_as_observed(product, bad):
    def handler(request):
        if "tools" in json.loads(request.content):
            return httpx.Response(200, json=web_response())
        payload = extraction_payload()
        finding = payload["demand_evidence"][0]
        if bad == "invented_url":
            finding["source_urls"] = ["https://invented.example.com/not-retrieved"]
        else:
            finding["supporting_excerpt"] = "An invented exact quote with no retrieved support."
        return httpx.Response(200, json=response_body(json.dumps(payload)))

    provider, client = provider_for(handler)
    with client:
        report = provider.research(product)
    assert report.demand_evidence == []
    assert report.dimensions.demand == "unknown"
    assert report.status == "insufficient"
    assert report.research_summary == "Insufficient evidence"
    assert all(s.url != "https://invented.example.com/not-retrieved" for s in report.sources)


def test_excerpt_cannot_be_assigned_to_an_unrelated_citation(product):
    def handler(request):
        if "tools" in json.loads(request.content):
            return httpx.Response(200, json=web_response())
        payload = extraction_payload()
        payload["demand_evidence"][0]["source_urls"] = [URLS[2]]
        return httpx.Response(200, json=response_body(json.dumps(payload)))

    provider, client = provider_for(handler)
    with client:
        report = provider.research(product)
    assert report.demand_evidence == []


def test_same_paragraph_does_not_transfer_a_claim_to_an_unrelated_source(product):
    def handler(request):
        if "tools" in json.loads(request.content):
            data = web_response()
            part = data["output"][1]["content"][0]
            part["text"] = part["text"].replace("\n", " ")
            return httpx.Response(200, json=data)
        payload = extraction_payload()
        payload["demand_evidence"][0]["source_urls"] = [URLS[2]]
        return httpx.Response(200, json=response_body(json.dumps(payload)))

    provider, client = provider_for(handler)
    with client:
        report = provider.research(product)
    assert report.demand_evidence == []
    assert report.dimensions.demand == "unknown"


def test_citation_markers_bind_the_preceding_claim_and_adjacent_markers_share_it(product):
    def handler(request):
        if "tools" in json.loads(request.content):
            text = QUOTES[0] + " [1][2] " + QUOTES[2] + " [3]"
            data = web_response()
            part = data["output"][1]["content"][0]
            part["text"] = text
            part["annotations"] = [
                {
                    "type": "url_citation",
                    "title": f"Source {i}",
                    "url": url,
                    "start_index": text.index(f"[{i + 1}]"),
                    "end_index": text.index(f"[{i + 1}]") + 3,
                }
                for i, url in enumerate(URLS)
            ]
            return httpx.Response(200, json=data)
        payload = extraction_payload()
        payload["demand_evidence"][0]["source_urls"] = URLS[:2]
        payload["competition_evidence"] = []
        payload["marketing_angles"] = []
        payload["common_customer_complaints"] = []
        return httpx.Response(200, json=response_body(json.dumps(payload)))

    provider, client = provider_for(handler)
    with client:
        report = provider.research(product)
    assert len(report.demand_evidence) == 1
    assert len(report.demand_evidence[0].source_ids) == 2
    assert report.trend_evidence[0].supporting_excerpt == QUOTES[2]


@pytest.mark.parametrize(
    "kind", ["unauthorized", "timeout", "malformed", "refusal", "failed_search"]
)
def test_failed_external_calls_raise_sanitized_provider_error(product, kind):
    from src.research.providers.base import ResearchProviderError

    def handler(request):
        if kind == "timeout":
            raise httpx.ReadTimeout("test-secret internal error", request=request)
        if kind == "unauthorized":
            return httpx.Response(401, json={"error": {"message": "test-secret", "type": "auth"}})
        data = web_response()
        if kind == "failed_search":
            data["output"][0]["status"] = "failed"
        elif "tools" not in json.loads(request.content):
            data = response_body("{}" if kind == "malformed" else "", refusal=kind == "refusal")
        return httpx.Response(200, json=data)

    provider, client = provider_for(handler)
    with client, pytest.raises(ResearchProviderError) as error:
        provider.research(product)
    assert "test-secret" not in str(error.value)


def test_jsonld_prices_require_matching_product_and_usd():
    from src.research.providers.prices import parse_listing_prices

    html = """<script type="application/ld+json">{"@graph":[
      {"@type":"Product","name":"Reusable Pet Hair Remover roller",
       "offers":[{"@type":"Offer","price":"19.99","priceCurrency":"USD"},
                 {"@type":"Offer","price":"18.99","priceCurrency":"EUR"}]},
      {"@type":"Product","name":"Unrelated laptop","offers":{"price":"999","priceCurrency":"USD"}}
    ]}</script>"""
    rows = parse_listing_prices(html, "Pet Hair Remover", "source-id")
    assert len(rows) == 1
    assert rows[0].price == 19.99 and rows[0].source_id == "source-id"
    assert parse_listing_prices("<p>AI guesses price USD 19.99</p>", "Pet Hair Remover", "id") == []


def test_metadata_loader_never_fetches_nonallowlisted_or_local_urls():
    from src.research.models import Source, utc_now
    from src.research.providers.prices import fetch_listing_prices

    def never_call(request):
        pytest.fail("Untrusted domains must not be fetched")

    source = Source(
        title="Other source",
        url="https://untrusted.example.com/item",
        accessed_at=utc_now(),
        source_type="web",
        what_claim_it_supports="Cited claim",
    )
    with httpx.Client(transport=httpx.MockTransport(never_call)) as client:
        assert fetch_listing_prices(source, "Pet Hair Remover", client=client) == []


def test_midflow_api_failure_keeps_real_retrieved_citations_without_invented_analysis(product):
    from src.research.providers.base import ResearchProviderError

    def handler(request):
        if "tools" in json.loads(request.content):
            return httpx.Response(200, json=web_response())
        return httpx.Response(
            429,
            json={
                "error": {"message": "test-secret", "type": "quota", "code": "insufficient_quota"}
            },
        )

    provider, client = provider_for(handler)
    with client, pytest.raises(ResearchProviderError) as error:
        provider.research(product)
    partial = error.value.partial_report
    assert partial.status == "failed" and len(partial.sources) == 3
    assert partial.demand_evidence == [] and partial.confidence_level == "low"
    assert "test-secret" not in str(error.value)


@pytest.mark.parametrize("mislocated", [False, True])
def test_parenthesized_markdown_citations_bind_claims_even_with_inaccurate_annotation_offsets(
    product, mislocated
):
    def handler(request):
        if "tools" not in json.loads(request.content):
            return httpx.Response(200, json=response_body(json.dumps(extraction_payload())))
        pieces = []
        annotations = []
        cursor = 0
        for i, (quote, url) in enumerate(zip(QUOTES, [*URLS, URLS[0], URLS[0]], strict=True)):
            marker = f"([publisher{i}.com]({url}?utm_source=openai))"
            pieces.append(quote + " " + marker)
            start = cursor + len(quote) + 1
            annotations.append(
                {
                    "type": "url_citation",
                    "title": f"Source {i}",
                    "url": url,
                    "start_index": start,
                    "end_index": start + len(marker),
                }
            )
            cursor += len(pieces[-1]) + 1
        data = web_response()
        part = data["output"][1]["content"][0]
        part["text"] = " ".join(pieces)
        if mislocated:
            annotations[0]["start_index"] = annotations[2]["start_index"]
            annotations[0]["end_index"] = annotations[2]["end_index"]
        part["annotations"] = annotations
        return httpx.Response(200, json=data)

    provider, client = provider_for(handler)
    with client:
        report = provider.research(product)
    assert report.status == "completed"
    assert report.demand_evidence[0].supporting_excerpt == QUOTES[0]
    assert report.competition_evidence[0].supporting_excerpt == QUOTES[1]
    assert report.trend_evidence[0].supporting_excerpt == QUOTES[2]
