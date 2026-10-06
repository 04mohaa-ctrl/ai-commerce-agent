"""Complete simulated external responses; no real research claims."""

from tests.test_agent import response_body

URLS = [
    "https://publisher0.com/pet-hair",
    "https://publisher1.com/rollers",
    "https://publisher2.com/pet-care",
]
QUOTES = [
    "Recent reviews discuss interest in reusable pet hair removers.",
    "Multiple retailers offer comparable reusable rollers, suggesting broad competition.",
    "Recent publications describe ongoing interest; a rising sales trend is not established.",
    "Demonstrations of fur removed from upholstery are common in marketing.",
    "Some reviewers mention repeated passes on certain fabrics.",
]


def extraction_payload():
    fields = [
        "demand_evidence",
        "competition_evidence",
        "trend_evidence",
        "marketing_angles",
        "common_customer_complaints",
    ]
    payload = {
        "research_summary": "Current cited sources describe reusable hair-removal rollers.",
        "dimensions": {
            "demand": "strong",
            "competition": "moderate",
            "trend": "moderate",
            "marketing": "strong",
        },
        "risks": ["Retail listings do not verify sales."],
    }
    for field, quote, url in zip(fields, QUOTES, [*URLS, URLS[0], URLS[0]], strict=True):
        payload[field] = [{"claim": quote, "supporting_excerpt": quote, "source_urls": [url]}]
    return payload


def web_response(*, citations=True, duplicate=False):
    text = "\n".join(QUOTES)
    data = response_body(text)
    annotations = [
        {
            "type": "url_citation",
            "title": f"Cited page {i}",
            "url": url,
            "start_index": text.index(quote),
            "end_index": text.index(quote) + len(quote),
        }
        for i, (quote, url) in enumerate(zip(QUOTES, [*URLS, URLS[0], URLS[0]], strict=True))
    ]
    if duplicate:
        annotations.append(dict(annotations[0], url=URLS[0] + "?utm_source=chatgpt#top"))
    data["output"][0]["content"][0]["annotations"] = annotations if citations else []
    data["output"].insert(
        0,
        {
            "id": "ws_test",
            "type": "web_search_call",
            "status": "completed",
            "action": {
                "type": "search",
                "query": "pet hair remover current reviews",
                "sources": [{"type": "url", "url": url} for url in URLS],
            },
        },
    )
    return data


def report_fixture():
    from src.research.models import (
        EvidenceFinding,
        QualitativeDimensions,
        ResearchReport,
        Source,
        utc_now,
    )

    sources = [
        Source(
            title=f"Cited page {i}",
            url=url,
            accessed_at=utc_now(),
            source_type="web",
            what_claim_it_supports=QUOTES[i],
        )
        for i, url in enumerate(URLS)
    ]
    fields = [
        "demand_evidence",
        "competition_evidence",
        "trend_evidence",
        "marketing_angles",
        "common_customer_complaints",
    ]
    evidence = {
        field: [EvidenceFinding(claim=quote, supporting_excerpt=quote, source_ids=[source.id])]
        for field, quote, source in zip(
            fields, QUOTES, [*sources, sources[0], sources[0]], strict=True
        )
    }
    return ResearchReport(
        product_name="Pet Hair Remover",
        status="completed",
        sources=sources,
        research_summary="Current cited sources describe reusable hair-removal rollers.",
        dimensions=QualitativeDimensions(
            demand="strong", competition="moderate", trend="moderate", marketing="strong"
        ),
        **evidence,
    )
