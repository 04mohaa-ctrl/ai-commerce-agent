"""Isolated regressions for the final independent review; no provider requests."""

import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.database.database import ProductRepository
from src.database.supply_repository import SupplyRepository
from src.discovery.repository import DiscoveryRepository
from src.research.providers.safe_http import _DeadlineBackend, _Rejected


def test_dns_deadline_prevents_connect_after_slow_resolution(monkeypatch):
    release = threading.Event()
    calls = []

    def stalled(*args, **kwargs):
        release.wait(2)
        return [(None, None, None, None, ("203.0.113.1", 443))]

    monkeypatch.setattr("socket.getaddrinfo", stalled)
    backend = _DeadlineBackend(time.monotonic() + 0.04, time.monotonic)
    monkeypatch.setattr(backend.backend, "connect_tcp", lambda *a, **k: calls.append(a))
    start = time.monotonic()
    try:
        with pytest.raises(_Rejected, match="deadline"):
            backend.connect_tcp("api.dataforseo.com", 443)
        assert time.monotonic() - start < 0.5
        assert calls == []
    finally:
        release.set()


@pytest.mark.parametrize("start_version", [2, 3, 4])
def test_parallel_migrations_keep_only_schema4_rollback_snapshots(tmp_path, start_version):
    repo = ProductRepository(tmp_path / "race.db")
    if start_version == 3:
        from src.database.market_repository import MarketIntelligenceRepository

        MarketIntelligenceRepository(repo, backup_dir=tmp_path / "b3").enable()
    if start_version == 4:
        SupplyRepository(repo, backup_dir=tmp_path / "b4").enable()
    barrier = threading.Barrier(2)

    def activate():
        barrier.wait()
        DiscoveryRepository(repo, backup_dir=tmp_path / "b5").enable()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: activate(), range(2)))
    backups = list((tmp_path / "b5").glob("*.db"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
    assert ProductRepository(backups[0]).list_saved() == []


def test_cj_uses_absolute_deadline_without_retry(monkeypatch):
    from src.supply.cj_transport import CJResearchTransport
    from src.supply.models import ActionTelemetry

    monkeypatch.setenv("CJ_API_KEY", "fixture-deadline")
    seen = []

    class DeadlineTransport:
        def __init__(self, deadline, monotonic):
            seen.append(deadline)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def close(self):
            pass

        def handle_request(self, request):
            raise _Rejected("DNS deadline exceeded.", "unavailable")

    monkeypatch.setattr("src.research.providers.safe_http._DeadlineTransport", DeadlineTransport)
    transport = CJResearchTransport(monotonic=lambda: 100, retry_limit=0)
    transport.reset_action(ActionTelemetry(), max_requests=2, max_seconds=30)
    outcome = transport.request("search", {"keyWord": "laptop stand", "page": 1, "size": 10})
    assert outcome.status == "BUDGET_EXHAUSTED"
    assert outcome.limit_source == "LOCAL_TIME_BUDGET"
    assert seen == [130]
    assert transport.telemetry.requests == {"auth": 1}
