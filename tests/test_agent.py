import json

import httpx
import pytest
from openai import OpenAI

from src.schemas.product import Assessment


def make_client(handler):
    return OpenAI(
        api_key="test-secret",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def response_body(text, *, refusal=False):
    content = (
        {"type": "refusal", "refusal": "Cannot analyze"}
        if refusal
        else {"type": "output_text", "text": text, "annotations": [], "logprobs": []}
    )
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 1,
        "status": "completed",
        "model": "gpt-4o-mini",
        "error": None,
        "incomplete_details": None,
        "instructions": None,
        "metadata": {},
        "output": [
            {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [content],
            }
        ],
        "parallel_tool_calls": False,
        "temperature": 1,
        "tool_choice": "auto",
        "tools": [],
        "top_p": 1,
    }


def test_missing_key_uses_repeatable_demo_without_network(product):
    from src.agents.product_research_agent import ProductResearchAgent

    agent = ProductResearchAgent(api_key="")
    a, b = agent.analyze(product), agent.analyze(product)
    assert a.mode == "demo"
    assert a.assessment == b.assessment
    assert a.score == b.score
    assert a.product.evidence == []
    assert "verified" in a.assessment.uncertainty.lower()
    assert a.assessment.risks and a.assessment.next_steps


def test_explicit_demo_does_not_call_api_even_with_key(product):
    from src.agents.product_research_agent import ProductResearchAgent

    def never_call(request):
        pytest.fail("Demo must not call the network")

    with make_client(never_call) as client:
        result = ProductResearchAgent(
            api_key="test-secret", force_demo=True, client=client
        ).analyze(product)
    assert result.mode == "demo"


def test_live_output_is_structured_and_score_remains_deterministic(product):
    from src.agents.product_research_agent import ProductResearchAgent

    seen = []
    assessment = Assessment(
        demand=8,
        competition=4,
        trend=7,
        marketing=9,
        explanation="Estimated candidate, no verified market evidence.",
    )

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=response_body(assessment.model_dump_json()))

    with make_client(handler) as client:
        result = ProductResearchAgent(api_key="test-secret", client=client).analyze(product)
    assert result.mode == "openai"
    # 20 + 20 (80% margin) + 14 + 9 + 13.5 = 76.5.
    assert result.score.total == 76.5
    assert result.recommendation == "Strong candidate"
    assert result.product.evidence == []
    assert seen[0]["text"]["format"]["type"] == "json_schema"
    assert seen[0]["store"] is False
    assert json.loads(seen[0]["input"][0]["content"])["name"] == product.name


@pytest.mark.parametrize("kind", ["unauthorized", "timeout", "invalid", "refusal"])
def test_live_failures_fall_back_with_sanitized_notice(product, kind):
    from src.agents.product_research_agent import ProductResearchAgent

    def handler(request):
        if kind == "timeout":
            raise httpx.ReadTimeout("test-secret in internal error", request=request)
        if kind == "unauthorized":
            return httpx.Response(401, json={"error": {"message": "test-secret", "type": "auth"}})
        if kind == "invalid":
            return httpx.Response(200, json=response_body('{"demand": 100}'))
        return httpx.Response(200, json=response_body("", refusal=True))

    with make_client(handler) as client:
        result = ProductResearchAgent(api_key="test-secret", client=client).analyze(product)
    assert result.mode == "demo"
    assert result.notice
    assert "test-secret" not in result.notice
    assert result.score.total >= 0


def test_live_result_cannot_promote_generated_claims_to_verified_data(product):
    from src.agents.product_research_agent import ProductResearchAgent

    def handler(request):
        text = Assessment(demand=8, competition=4, trend=7, marketing=9).model_dump()
        text["verified_data"] = ["Fictional 100% growth"]
        return httpx.Response(200, json=response_body(json.dumps(text)))

    with make_client(handler) as client:
        result = ProductResearchAgent(api_key="test-secret", client=client).analyze(product)
    assert result.mode == "demo"
    assert result.product.evidence == []
