"""Offline proof of the exact live-acceptance scope; fixtures are never live evidence."""

import json
from datetime import UTC, datetime

import httpx
import pytest

from src.database.database import ProductRepository
from src.supply.cj_transport import CJResearchTransport
from tests.test_cj_transport import Clock, auth


def test_acceptance_has_no_automatic_auth_or_catalog_retry(monkeypatch):
    monkeypatch.setenv("CJ_API_KEY", "fixture-no-retry")
    clock = Clock()
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(503)

    transport = CJResearchTransport(
        http_transport=httpx.MockTransport(handler),
        clock=clock.now,
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
        retry_limit=0,
    )
    outcome = transport.request("search", {"keyWord": "laptop stand", "page": 1, "size": 10})
    assert outcome.status == "FAILED"
    assert calls == ["/api2.0/v1/authentication/getAccessToken"]
    assert transport.telemetry.retries == 0


def test_acceptance_catalog_failure_is_not_retried(monkeypatch):
    from src.supply.models import ActionTelemetry

    monkeypatch.setenv("CJ_API_KEY", "fixture-catalog-no-retry")
    clock, calls = Clock(), []

    def handler(request):
        calls.append(request.url.path)
        return (
            httpx.Response(200, json=auth(clock))
            if "authentication" in request.url.path
            else httpx.Response(503)
        )

    transport = CJResearchTransport(
        http_transport=httpx.MockTransport(handler),
        retry_limit=0,
        clock=clock.now,
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
    )
    transport.reset_action(ActionTelemetry(), max_requests=2, max_seconds=30)
    assert (
        transport.request("search", {"keyWord": "laptop stand", "page": 1, "size": 10}).status
        == "FAILED"
    )
    assert len(calls) == 2 and transport.telemetry.retries == 0


def test_prepare_is_empty_offline_and_never_overwrites(tmp_path):
    from scripts.v5_live_acceptance import prepare

    path, folder = tmp_path / "live.db", tmp_path / "evidence"
    scope = prepare(path, folder)
    assert scope["search"] == {"keyWord": "laptop stand", "page": 1, "size": 10}
    assert scope["max_http_requests"] == 2 and scope["max_catalog_requests"] == 1
    assert scope["documented_points"] == 50
    repo = ProductRepository(path)
    assert repo.list_saved() == repo.list_candidates() == []
    assert (folder / "scope.json").exists()
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        prepare(path, folder)
    assert path.read_bytes() == before


def test_capture_requires_matching_approval_before_provider_construction(tmp_path):
    from scripts.v5_live_acceptance import capture, prepare

    path, folder = tmp_path / "live.db", tmp_path / "evidence"
    prepare(path, folder)
    with pytest.raises(ValueError, match="approval"):
        capture(path, folder, approval="not-the-approved-scope")
    assert not (folder / "attempt-started.json").exists()


def test_capture_once_finish_and_restart_without_provider_followups(tmp_path, monkeypatch):
    from scripts.v5_live_acceptance import capture, finish, prepare
    from src.supply.cj_provider import CJDropShippingProvider

    path, folder = tmp_path / "live.db", tmp_path / "evidence"
    scope = prepare(path, folder)
    calls = []
    clock = Clock()
    monkeypatch.setenv("CJ_API_KEY", "fixture-acceptance-complete")

    def handler(request):
        calls.append(request.url.path)
        if "authentication" in request.url.path:
            return httpx.Response(200, json=auth(clock))
        assert request.url.path.endswith("/product/listV2")
        assert dict(request.url.params) == {"keyWord": "laptop stand", "page": "1", "size": "10"}
        return httpx.Response(
            200,
            json={
                "code": 200,
                "result": True,
                "data": {
                    "content": [
                        {
                            "productList": [
                                {
                                    "id": f"fixture-{n}",
                                    "nameEn": f"Laptop stand {n}",
                                    "sellPrice": "5.00",
                                }
                                for n in range(3)
                            ]
                        }
                    ]
                },
            },
        )

    provider = CJDropShippingProvider(
        transport=CJResearchTransport(
            http_transport=httpx.MockTransport(handler),
            retry_limit=0,
            clock=clock.now,
            monotonic=clock.monotonic,
            sleeper=clock.sleep,
        )
    )
    result = capture(
        path,
        folder,
        approval=scope["approval_id"],
        provider=provider,
        evidence_class="OFFLINE_FIXTURE",
    )
    assert len(result.outcome.records) == 3
    assert calls == ["/api2.0/v1/authentication/getAccessToken", "/api2.0/v1/product/listV2"]
    capture(
        path,
        folder,
        approval=scope["approval_id"],
        provider=provider,
        evidence_class="OFFLINE_FIXTURE",
    )  # durable capture reuse, no second catalog request
    document = finish(path, folder, [f"fixture-{n}" for n in range(3)])
    assert len(document["products"]) == 3
    assert document["acceptance"]["evidence_class"] == "OFFLINE_FIXTURE"
    assert all(p["demand"] is None for p in document["products"])
    assert all(
        p["financial"]["calculation"]["economics"]["estimated_net_profit"] is None
        for p in document["products"]
    )
    assert len(ProductRepository(path).list_saved()) == 3
    assert len(calls) == 2
    from src.discovery.comparison import ComparisonGroup, save_group
    from src.discovery.repository import DiscoveryRepository

    group = ComparisonGroup.model_validate(document["group"])
    group.decision, group.notes = "Hold", "Operator reviewed these candidates"
    save_group(ProductRepository(path), group)
    finish(path, folder, [f"fixture-{n}" for n in range(3)])
    assert DiscoveryRepository(ProductRepository(path)).list_groups()[0]["decision"] == "Hold"
    before = path.read_bytes()
    with pytest.raises(ValueError, match="other IDs"):
        finish(path, folder, ["fixture-1", "fixture-2", "fixture-3"])
    assert path.read_bytes() == before
    assert len(ProductRepository(path).list_saved()) == 3
    assert len(calls) == 2
    with pytest.raises(ValueError, match="relabeled"):
        capture(path, folder, approval=scope["approval_id"], provider=provider)

    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("DATABASE_PATH", str(path))
    monkeypatch.setenv("COMMERCE_OFFLINE", "1")
    monkeypatch.setenv("V5_ACCEPTANCE_FOLDER", str(folder))
    app_path = Path(__file__).resolve().parents[1] / "scripts" / "v5_acceptance_app.py"
    app = AppTest.from_file(str(app_path), default_timeout=30).run()
    for page in ["Discover", "Candidates", "Compare", "Dashboard", "Compare"]:
        app.sidebar.radio("nav").set_value(page).run()
        assert not app.exception
    assert app.text_input("v5_group_name").value == "V5 catalog acceptance"
    assert len(app.multiselect("v5_group_members").value) == 3
    assert len(calls) == 2
    fresh = AppTest.from_file(str(app_path), default_timeout=30).run()
    fresh.sidebar.radio("nav").set_value("Compare").run()
    assert fresh.text_input("v5_group_name").value == "V5 catalog acceptance"
    assert fresh.session_state["results"] == []
    assert len(calls) == 2


def test_uncertain_capture_never_resubmits_and_insufficient_results_do_not_expand(tmp_path):
    from scripts.v5_live_acceptance import capture, finish, prepare
    from src.discovery.models import DiscoveryResult, DiscoverySearch
    from src.supply.models import ActionTelemetry, ProviderOutcome

    path, folder = tmp_path / "live.db", tmp_path / "evidence"
    scope = prepare(path, folder)
    (folder / "attempt-started.json").write_text("{}")
    with pytest.raises(RuntimeError, match="uncertain"):
        capture(path, folder, approval=scope["approval_id"])
    result = DiscoveryResult(
        search=DiscoverySearch(query="laptop stand"),
        outcome=ProviderOutcome(status="SUCCESS_EMPTY"),
        telemetry=ActionTelemetry(),
        searched_at=datetime.now(UTC),
    )
    (folder / "capture.json").write_text(result.model_dump_json())
    (folder / "capture-provenance.json").write_text(
        json.dumps({"evidence_class": "OFFLINE_FIXTURE"})
    )
    with pytest.raises(ValueError, match="three"):
        finish(path, folder, ["a", "b", "c"])
    assert ProductRepository(path).list_saved() == []
