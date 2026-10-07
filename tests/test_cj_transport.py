"""CJ HTTP-boundary fixtures: synthetic credentials, no network or rate sleeps."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest


class Clock:
    def __init__(self):
        self.seconds = 0.0
        self.start = datetime(2026, 10, 7, tzinfo=UTC)

    def now(self):
        return self.start + timedelta(seconds=self.seconds)

    def monotonic(self):
        return self.seconds

    def sleep(self, seconds):
        self.seconds += seconds


def auth(clock, *, lifetime=3600, access="fixture-access"):
    return {
        "code": 200,
        "result": True,
        "data": {
            "accessToken": access,
            "accessTokenExpiryDate": (clock.now() + timedelta(seconds=lifetime)).isoformat(),
            "refreshToken": "fixture-refresh",
            "refreshTokenExpiryDate": (clock.now() + timedelta(days=2)).isoformat(),
        },
    }


def make_transport(monkeypatch, handler, *, clock=None, credential=None):
    from src.supply.cj_transport import CJResearchTransport

    monkeypatch.setenv("CJ_API_KEY", credential or f"fixture-key-{uuid4()}")
    clock = clock or Clock()
    transport = CJResearchTransport(
        http_transport=httpx.MockTransport(handler),
        clock=clock.now,
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
    )
    return transport, clock


def test_missing_credential_never_dispatches(monkeypatch):
    from src.supply.cj_transport import CJResearchTransport

    monkeypatch.delenv("CJ_API_KEY", raising=False)
    transport = CJResearchTransport(http_transport=httpx.MockTransport(lambda _: pytest.fail()))
    assert transport.configured is False
    assert transport.request("search", {"keyWord": "box", "page": 1, "size": 10}).status == (
        "UNAVAILABLE"
    )
    assert transport.telemetry.requests == {}


@pytest.mark.parametrize(
    "operation,params",
    [
        ("https://attacker.invalid/", {}),
        ("../shopping/order/createOrder", {}),
        ("freightCalculateTip", {}),
        ("getAccessToken", {"apiKey": "caller-key"}),
        ("search", {"keyWord": "box", "page": 1, "size": 10, "url": "https://evil/"}),
        ("search", {"keyWord": "box", "page": 3, "size": 10}),
        ("details", {"pid": ""}),
        ("details", {"pid": "p", "headers": {"CJ-Access-Token": "other"}}),
        ("shipping", {"startCountryCode": "CN", "endCountryCode": "US", "products": []}),
        ("stock", {"vid": "v", "method": "POST"}),
    ],
)
def test_invalid_operations_or_parameters_never_dispatch(monkeypatch, operation, params):
    transport, _ = make_transport(monkeypatch, lambda _: pytest.fail("must reject before auth"))
    assert transport.request(operation, params).status == "UNSUPPORTED"
    assert transport.telemetry.requests == {}


def test_exact_url_method_headers_spacing_and_no_cookie_reuse(monkeypatch):
    clock = Clock()
    observed = []

    def handler(request):
        observed.append((request.method, str(request.url), dict(request.headers), clock.seconds))
        if len(observed) == 1:
            assert b'"apiKey"' in request.content
            return httpx.Response(200, json=auth(clock), headers={"Set-Cookie": "private=secret"})
        return httpx.Response(200, json={"code": 200, "result": True, "data": []})

    transport, _ = make_transport(monkeypatch, handler, clock=clock)
    assert transport.request("search", {"keyWord": "box", "page": 1, "size": 10}).status == (
        "SUCCESS"
    )
    assert observed[0][:2] == (
        "POST",
        "https://developers.cjdropshipping.com/api2.0/v1/authentication/getAccessToken",
    )
    assert observed[1][0] == "GET"
    assert observed[1][1] == (
        "https://developers.cjdropshipping.com/api2.0/v1/product/listV2?keyWord=box&page=1&size=10"
    )
    assert observed[1][2]["cj-access-token"] == "fixture-access"
    assert "cookie" not in observed[1][2]
    assert observed[1][3] - observed[0][3] >= 1
    assert transport.telemetry.requests == {"auth": 1, "search": 1}


def test_expiry_refresh_uses_returned_dates_and_cache_is_credential_scoped(monkeypatch):
    clock = Clock()
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if "authentication" in request.url.path:
            return httpx.Response(200, json=auth(clock, lifetime=120))
        return httpx.Response(200, json={"code": 200, "result": True, "data": []})

    credential = f"fixture-key-{uuid4()}"
    first, _ = make_transport(monkeypatch, handler, clock=clock, credential=credential)
    first.request("stock", {"vid": "v"})
    second, _ = make_transport(monkeypatch, handler, clock=clock, credential=credential)
    second.request("stock", {"vid": "v"})
    assert second.telemetry.requests == {"stock": 1}
    assert "cj_token" in second.telemetry.cache_hits
    clock.sleep(61)
    second.request("stock", {"vid": "v"})
    assert paths.count("/api2.0/v1/authentication/refreshAccessToken") == 1
    third, _ = make_transport(monkeypatch, handler, clock=clock)
    third.request("stock", {"vid": "v"})
    assert paths.count("/api2.0/v1/authentication/getAccessToken") == 2


def test_concurrent_provider_instances_share_one_locked_auth(monkeypatch):
    clock = Clock()
    credential = f"fixture-key-{uuid4()}"

    def handler(request):
        if "authentication" in request.url.path:
            return httpx.Response(200, json=auth(clock))
        return httpx.Response(200, json={"code": 200, "result": True, "data": []})

    transports = [
        make_transport(monkeypatch, handler, clock=clock, credential=credential)[0]
        for _ in range(4)
    ]
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda t: t.request("stock", {"vid": "v"}), transports))
    assert all(result.status == "SUCCESS" for result in results)
    assert sum(t.telemetry.requests.get("auth", 0) for t in transports) == 1
    assert clock.seconds >= 4


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_redirect_is_rejected_without_following_or_leaking(monkeypatch, status):
    clock = Clock()

    def handler(request):
        assert request.url.host == "developers.cjdropshipping.com"
        if "authentication" in request.url.path:
            return httpx.Response(200, json=auth(clock))
        return httpx.Response(status, headers={"Location": "https://attacker.invalid/token"})

    transport, _ = make_transport(monkeypatch, handler, clock=clock)
    outcome = transport.request("stock", {"vid": "v"})
    assert outcome.status == "FAILED"
    assert transport.telemetry.requests == {"auth": 1, "stock": 1}
    assert "attacker" not in outcome.notice


def test_every_dispatch_counts_budget_and_reset_binds_new_telemetry(monkeypatch):
    from src.supply.models import ActionTelemetry

    clock = Clock()

    def handler(request):
        if "authentication" in request.url.path:
            return httpx.Response(200, json=auth(clock))
        return httpx.Response(200, json={"code": 200, "result": True, "data": []})

    transport, _ = make_transport(monkeypatch, handler, clock=clock)
    old = transport.telemetry
    transport.reset_action(old, max_requests=2)
    assert transport.request("stock", {"vid": "v"}).status == "SUCCESS"
    exhausted = transport.request("stock", {"vid": "v"})
    assert exhausted.status == "BUDGET_EXHAUSTED"
    assert exhausted.limit_source == "LOCAL_REQUEST_BUDGET"
    assert sum(old.requests.values()) == 2
    new = ActionTelemetry(action="refresh_shipping")
    transport.reset_action(new, max_requests=4)
    assert transport.request("stock", {"vid": "v"}).status == "SUCCESS"
    assert new.requests == {"stock": 1}
    assert sum(old.requests.values()) == 2


@pytest.mark.parametrize(
    "retry_after,expected_status,stock_calls", [("3", "SUCCESS", 2), ("100", "RATE_LIMITED", 1)]
)
def test_retry_after_respects_deadline_and_one_retry(
    monkeypatch, retry_after, expected_status, stock_calls
):
    clock = Clock()
    attempts = 0

    def handler(request):
        nonlocal attempts
        if "authentication" in request.url.path:
            return httpx.Response(200, json=auth(clock))
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": retry_after})
        return httpx.Response(200, json={"code": 200, "result": True, "data": []})

    transport, _ = make_transport(monkeypatch, handler, clock=clock)
    assert transport.request("stock", {"vid": "v"}).status == expected_status
    assert transport.telemetry.requests["stock"] == stock_calls
    assert transport.telemetry.retries == stock_calls - 1
    assert clock.seconds < 90


@pytest.mark.parametrize(
    "code,status,retries",
    [
        (1600200, "RATE_LIMITED", 0),
        (1600201, "RATE_LIMITED", 0),
        (16900500, "RATE_LIMITED", 0),
        (1600000, "FAILED", 1),
        (1600301, "FAILED", 1),
        (1600100, "FAILED", 0),
    ],
)
def test_typed_provider_codes_discard_raw_messages(monkeypatch, code, status, retries):
    clock = Clock()

    def handler(request):
        if "authentication" in request.url.path:
            return httpx.Response(200, json=auth(clock))
        return httpx.Response(
            200,
            json={
                "code": code,
                "result": False,
                "message": "fixture-access fixture-refresh private-body",
                "data": {"token": "sensitive"},
            },
        )

    transport, _ = make_transport(monkeypatch, handler, clock=clock)
    result = transport.request("stock", {"vid": "v"})
    assert result.status == status
    if status == "RATE_LIMITED":
        assert result.limit_source == "PROVIDER_QUOTA_LIMIT"
        assert result.code == code
    assert result.data is None
    assert transport.telemetry.retries == retries
    assert "fixture-" not in repr(result)
    assert "private-body" not in result.notice


def test_auth_error_is_recovered_once_without_echoing_secrets(monkeypatch):
    clock = Clock()
    attempts = 0

    def handler(request):
        nonlocal attempts
        if "authentication" in request.url.path:
            return httpx.Response(200, json=auth(clock))
        attempts += 1
        if attempts == 1:
            return httpx.Response(200, json={"code": 1600002, "result": False, "message": "secret"})
        return httpx.Response(200, json={"code": 200, "result": True, "data": []})

    transport, _ = make_transport(monkeypatch, handler, clock=clock)
    assert transport.request("stock", {"vid": "v"}).status == "SUCCESS"
    assert transport.telemetry.requests == {"auth": 1, "stock": 2, "auth_refresh": 1}
    assert transport.telemetry.retries == 1
    assert "fixture-" not in repr(transport)


@pytest.mark.parametrize("kind", ["oversize", "malformed", "bad_envelope", "timeout"])
def test_bounded_response_and_sanitized_transport_failures(monkeypatch, kind):
    clock = Clock()

    def handler(request):
        if "authentication" in request.url.path:
            return httpx.Response(200, json=auth(clock))
        if kind == "oversize":
            return httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 1))
        if kind == "malformed":
            return httpx.Response(200, content=b"fixture-access not JSON")
        if kind == "bad_envelope":
            return httpx.Response(200, json={"data": []})
        raise httpx.ReadTimeout("secret fixture-access", request=request)

    transport, _ = make_transport(monkeypatch, handler, clock=clock)
    result = transport.request("stock", {"vid": "v"})
    assert result.status == "FAILED"
    assert result.data is None
    assert "fixture-access" not in result.notice
    assert sum(transport.telemetry.requests.values()) <= 3


def test_malformed_or_expired_token_dates_do_not_authorize_catalog(monkeypatch):
    clock = Clock()

    def handler(request):
        assert "authentication" in request.url.path
        data = auth(clock, lifetime=-10)
        return httpx.Response(200, json=data)

    transport, _ = make_transport(monkeypatch, handler, clock=clock)
    assert transport.request("stock", {"vid": "v"}).status == "FAILED"
    assert transport.telemetry.requests == {"auth": 1}


def test_default_budget_stops_after_twelve_dispatches_including_auth(monkeypatch):
    clock = Clock()

    def handler(request):
        if "authentication" in request.url.path:
            return httpx.Response(200, json=auth(clock))
        return httpx.Response(200, json={"code": 200, "result": True, "data": []})

    transport, _ = make_transport(monkeypatch, handler, clock=clock)
    for _ in range(11):
        assert transport.request("stock", {"vid": "v"}).status == "SUCCESS"
    outcome = transport.request("stock", {"vid": "v"})
    assert outcome.status == "BUDGET_EXHAUSTED"
    assert outcome.limit_source == "LOCAL_REQUEST_BUDGET"
    assert transport.telemetry.requests == {"auth": 1, "stock": 11}


def test_expired_refresh_reacquires_instead_of_trying_expired_token(monkeypatch):
    clock = Clock()
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if "authentication" in request.url.path:
            data = auth(clock, lifetime=120)
            data["data"]["refreshTokenExpiryDate"] = (
                clock.now() + timedelta(seconds=120)
            ).isoformat()
            return httpx.Response(200, json=data)
        return httpx.Response(200, json={"code": 200, "result": True, "data": []})

    transport, _ = make_transport(monkeypatch, handler, clock=clock)
    transport.request("stock", {"vid": "v"})
    clock.sleep(130)
    transport.reset_action(transport.telemetry)
    assert transport.request("stock", {"vid": "v"}).status == "SUCCESS"
    assert paths.count("/api2.0/v1/authentication/getAccessToken") == 2
    assert not any("refreshAccessToken" in path for path in paths)


def test_failed_refresh_reacquires_once_without_unbounded_auth_loop(monkeypatch):
    clock = Clock()

    def handler(request):
        if "refreshAccessToken" in request.url.path:
            return httpx.Response(200, json={"code": 1600003, "result": False, "message": "secret"})
        if "getAccessToken" in request.url.path:
            return httpx.Response(200, json=auth(clock, lifetime=120))
        return httpx.Response(200, json={"code": 200, "result": True, "data": []})

    transport, _ = make_transport(monkeypatch, handler, clock=clock)
    transport.request("stock", {"vid": "v"})
    clock.sleep(61)
    assert transport.request("stock", {"vid": "v"}).status == "SUCCESS"
    assert transport.telemetry.requests == {"auth": 2, "auth_refresh": 1, "stock": 2}
    assert transport.telemetry.retries == 1


def test_http_date_retry_after_is_respected(monkeypatch):
    clock = Clock()
    calls = 0
    observed = []

    def handler(request):
        nonlocal calls
        if "authentication" in request.url.path:
            return httpx.Response(200, json=auth(clock))
        observed.append(clock.seconds)
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "Wed, 07 Oct 2026 00:00:10 GMT"})
        return httpx.Response(200, json={"code": 200, "result": True, "data": []})

    transport, _ = make_transport(monkeypatch, handler, clock=clock)
    assert transport.request("stock", {"vid": "v"}).status == "SUCCESS"
    assert observed == [1, 10]


def test_deadline_blocks_dispatch_even_when_token_remains_valid(monkeypatch):
    clock = Clock()

    def handler(request):
        if "authentication" in request.url.path:
            return httpx.Response(200, json=auth(clock))
        return httpx.Response(200, json={"code": 200, "result": True, "data": []})

    transport, _ = make_transport(monkeypatch, handler, clock=clock)
    transport.request("stock", {"vid": "v"})
    clock.sleep(90)
    outcome = transport.request("stock", {"vid": "v"})
    assert outcome.status == "BUDGET_EXHAUSTED"
    assert outcome.limit_source == "LOCAL_TIME_BUDGET"
    assert transport.telemetry.requests == {"auth": 1, "stock": 1}


def test_proxy_environment_is_ignored_and_timeout_bounded(monkeypatch):
    clock = Clock()
    monkeypatch.setenv("HTTPS_PROXY", "http://attacker.invalid:8888")

    def handler(request):
        assert request.url.host == "developers.cjdropshipping.com"
        assert request.extensions["timeout"] == {
            "connect": 20.0,
            "read": 20.0,
            "write": 20.0,
            "pool": 20.0,
        }
        if "authentication" in request.url.path:
            return httpx.Response(200, json=auth(clock))
        return httpx.Response(200, json={"code": 200, "result": True, "data": []})

    transport, _ = make_transport(monkeypatch, handler, clock=clock)
    assert transport.request("stock", {"vid": "v"}).status == "SUCCESS"


def test_contradictory_success_flags_cannot_authorize_catalog(monkeypatch):
    clock = Clock()

    def handler(request):
        assert "authentication" in request.url.path
        data = auth(clock)
        data.update(result=False, success=True)
        return httpx.Response(200, json=data)

    transport, _ = make_transport(monkeypatch, handler, clock=clock)
    assert transport.request("stock", {"vid": "v"}).status == "FAILED"
    assert transport.telemetry.requests == {"auth": 1}


def test_auth_failure_updates_elapsed_without_returning_raw_data(monkeypatch):
    clock = Clock()

    def handler(request):
        clock.sleep(2)
        return httpx.Response(200, json={"code": 1600001, "result": False, "message": "secret"})

    transport, _ = make_transport(monkeypatch, handler, clock=clock)
    outcome = transport.request("stock", {"vid": "v"})
    assert outcome.status == "FAILED" and outcome.data is None
    assert transport.telemetry.elapsed_seconds == 2


def test_content_limit_applies_to_decoded_compressed_body(monkeypatch):
    import gzip

    clock = Clock()

    def handler(request):
        if "authentication" in request.url.path:
            return httpx.Response(200, json=auth(clock))
        compressed = gzip.compress(b"x" * (2 * 1024 * 1024 + 1))
        return httpx.Response(200, content=compressed, headers={"Content-Encoding": "gzip"})

    transport, _ = make_transport(monkeypatch, handler, clock=clock)
    assert transport.request("stock", {"vid": "v"}).status == "FAILED"
    assert transport.telemetry.requests == {"auth": 1, "stock": 1}


def test_cache_context_is_opaque_and_scoped_to_credential(monkeypatch):
    from uuid import UUID

    credential = f"fixture-key-{uuid4()}"
    first, _ = make_transport(monkeypatch, lambda _: pytest.fail(), credential=credential)
    second, _ = make_transport(monkeypatch, lambda _: pytest.fail(), credential=credential)
    third, _ = make_transport(monkeypatch, lambda _: pytest.fail())
    assert UUID(first.cache_context)
    assert first.cache_context == second.cache_context
    assert third.cache_context != first.cache_context
    assert credential not in first.cache_context
    assert first.telemetry.requests == {}


def test_cache_eviction_does_not_split_active_credential_locks(monkeypatch):
    clock = Clock()
    credential = f"fixture-key-{uuid4()}"

    def handler(request):
        if "authentication" in request.url.path:
            return httpx.Response(200, json=auth(clock))
        return httpx.Response(200, json={"code": 200, "result": True, "data": []})

    first, _ = make_transport(monkeypatch, handler, clock=clock, credential=credential)
    first.request("stock", {"vid": "v"})
    unrelated = [make_transport(monkeypatch, handler, clock=clock)[0] for _ in range(20)]
    assert len(unrelated) == 20
    second, _ = make_transport(monkeypatch, handler, clock=clock, credential=credential)
    assert second.cache_context == first.cache_context
    assert second.request("stock", {"vid": "v"}).status == "SUCCESS"
    assert second.telemetry.requests == {"stock": 1}


def test_retry_after_longer_than_action_remains_enforced_across_actions(monkeypatch):
    clock = Clock()

    def handler(request):
        if "authentication" in request.url.path:
            return httpx.Response(200, json=auth(clock))
        return httpx.Response(429, headers={"Retry-After": "100"})

    transport, _ = make_transport(monkeypatch, handler, clock=clock)
    outcome = transport.request("stock", {"vid": "v"})
    assert outcome.status == "RATE_LIMITED"
    assert outcome.limit_source == "PROVIDER_RATE_LIMIT"
    assert outcome.retry_blocked_by == "LOCAL_TIME_BUDGET"
    transport.reset_action(transport.telemetry)
    outcome = transport.request("stock", {"vid": "v"})
    assert outcome.status == "BUDGET_EXHAUSTED"
    assert outcome.limit_source == "LOCAL_TIME_BUDGET"
    assert transport.telemetry.requests == {"auth": 1, "stock": 1}
    assert clock.seconds == 1


def test_invalid_compressed_response_is_typed_failure(monkeypatch):
    clock = Clock()

    def handler(request):
        if "authentication" in request.url.path:
            return httpx.Response(200, json=auth(clock))
        return httpx.Response(
            200, stream=httpx.ByteStream(b"not-a-gzip-stream"), headers={"Content-Encoding": "gzip"}
        )

    transport, _ = make_transport(monkeypatch, handler, clock=clock)
    outcome = transport.request("stock", {"vid": "v"})
    assert outcome.status == "FAILED" and outcome.data is None
    assert transport.telemetry.requests == {"auth": 1, "stock": 1}


def test_transient_server_retry_after_is_honored_within_action(monkeypatch):
    clock = Clock()
    calls = []

    def handler(request):
        if "authentication" in request.url.path:
            return httpx.Response(200, json=auth(clock))
        calls.append(clock.seconds)
        if len(calls) == 1:
            return httpx.Response(503, headers={"Retry-After": "5"})
        return httpx.Response(200, json={"code": 200, "result": True, "data": []})

    transport, _ = make_transport(monkeypatch, handler, clock=clock)
    assert transport.request("stock", {"vid": "v"}).status == "SUCCESS"
    assert calls == [1, 6]
    assert transport.telemetry.retries == 1


def test_server_retry_after_beyond_action_reports_limited_and_keeps_cooldown(monkeypatch):
    clock = Clock()

    def handler(request):
        if "authentication" in request.url.path:
            return httpx.Response(200, json=auth(clock))
        return httpx.Response(503, headers={"Retry-After": "100"})

    transport, _ = make_transport(monkeypatch, handler, clock=clock)
    outcome = transport.request("stock", {"vid": "v"})
    assert outcome.status == "BUDGET_EXHAUSTED"
    assert outcome.limit_source == "LOCAL_TIME_BUDGET"
    transport.reset_action(transport.telemetry)
    assert transport.request("stock", {"vid": "v"}).status == "BUDGET_EXHAUSTED"
    assert transport.telemetry.requests == {"auth": 1, "stock": 1}
    assert transport.telemetry.retries == 0 and clock.seconds == 1
