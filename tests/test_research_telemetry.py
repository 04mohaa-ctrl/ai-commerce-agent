import json

import httpx
import pytest
from openai import OpenAI

from tests.research_fixtures import extraction_payload, web_response
from tests.test_agent import response_body


def test_actual_sdk_requests_and_observed_search_calls_are_counted(product):
    from src.research.providers.web_research import WebResearchProvider
    from src.research.telemetry import RunTelemetry

    run = RunTelemetry(model="fixture-model")

    def handler(request):
        payload = (
            web_response()
            if "tools" in json.loads(request.content)
            else response_body(json.dumps(extraction_payload()))
        )
        return httpx.Response(200, json=payload)

    with OpenAI(
        api_key="fixture-secret",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    ) as client:
        provider = WebResearchProvider(
            "fixture-secret", client=client, price_loader=lambda *args: [], telemetry=run.record
        )
        assert provider.research(product).sources
    assert run.openai_model_requests == 2
    assert run.web_search_calls == 1
    assert run.demand_requests == 0
    assert "fixture-secret" not in run.model_dump_json()
    second = RunTelemetry()
    assert second.openai_model_requests == 0 and second.web_search_calls == 0


def test_failed_request_is_counted_but_tool_usage_not_guessed(product):
    from src.research.providers.base import ResearchProviderError
    from src.research.providers.web_research import WebResearchProvider
    from src.research.telemetry import RunTelemetry

    run = RunTelemetry()
    with OpenAI(
        api_key="fixture-secret",
        max_retries=0,
        http_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(401, json={"error": {"message": "fixture-secret"}})
            )
        ),
    ) as client:
        provider = WebResearchProvider(
            "fixture-secret", client=client, price_loader=lambda *args: [], telemetry=run.record
        )
        with pytest.raises(ResearchProviderError) as caught:
            provider.research(product)
    assert run.openai_model_requests == 1
    assert run.web_search_calls is None
    assert "fixture-secret" not in str(caught.value)


@pytest.mark.parametrize("kind", ["non_json", "null_output"])
def test_uninspectable_success_response_has_unknown_tool_usage(product, kind):
    from src.research.providers.base import ResearchProviderError
    from src.research.providers.web_research import WebResearchProvider
    from src.research.telemetry import RunTelemetry

    run = RunTelemetry()

    def handler(request):
        if kind == "non_json":
            return httpx.Response(200, text="not json")
        data = web_response()
        data["output"] = None
        return httpx.Response(200, json=data)

    with OpenAI(
        api_key="fixture-secret",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    ) as client:
        with pytest.raises(ResearchProviderError):
            WebResearchProvider("fixture-secret", client=client, telemetry=run.record).research(
                product
            )
    assert run.openai_model_requests == 1
    assert run.web_search_calls is None
