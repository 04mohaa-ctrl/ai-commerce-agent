"""Local safeguards, recovery and retention are tested on isolated databases."""

import json
import sqlite3

import pytest

from src.database.database import ProductRepository
from tests.test_v5_comparison import saved


def test_backup_restore_export_and_delete(tmp_path):
    from src.database.maintenance import (
        backup_database,
        delete_product,
        export_database,
        restore_database,
    )
    from src.discovery.comparison import ComparisonGroup, save_group
    from src.discovery.queries import QueryPlan, QueryTerm, save_query_plan
    from src.discovery.repository import DiscoveryRepository

    repo = ProductRepository(tmp_path / "source.db")
    rows = saved(repo)
    ids = [r.product.id for r in rows]
    save_group(repo, ComparisonGroup(name="Retention", product_ids=ids, notes="Review"))
    save_query_plan(
        repo,
        rows[0].product,
        QueryPlan(country="SE", terms=[QueryTerm(query="ställ", language="sv")]),
    )
    backup = tmp_path / "backup.db"
    backup_database(repo.path, backup)
    original = backup.read_bytes()
    with pytest.raises(FileExistsError):
        backup_database(repo.path, backup)
    restored = tmp_path / "restore.db"
    restore_database(backup, restored)
    with pytest.raises(FileExistsError):
        restore_database(backup, repo.path)
    assert len(ProductRepository(restored).list_saved()) == 3
    export = export_database(repo)
    assert export["schema"] == "ai-commerce-local-export-1"
    assert "workspace_v5" in export["tables"]
    delete_product(repo, ids[0])
    assert len(repo.list_saved()) == 2
    serialized = json.dumps(export_database(repo))
    assert ids[0] not in serialized
    assert DiscoveryRepository(repo).list_groups() == []  # affected groups removed
    assert backup.read_bytes() == original
    with sqlite3.connect(restored) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_restore_rejects_invalid_source_and_never_overwrites(tmp_path):
    from src.database.maintenance import restore_database

    invalid = tmp_path / "invalid.db"
    invalid.write_bytes(b"not sqlite")
    target = tmp_path / "new.db"
    with pytest.raises((ValueError, sqlite3.DatabaseError)):
        restore_database(invalid, target)
    assert not target.exists()


def test_offline_mode_disables_credentials_and_all_network_boundaries(monkeypatch, product):
    from src.agents.product_research_agent import ProductResearchAgent
    from src.config import load_settings
    from src.research.providers.demand_trend import DataForSEOTrendProvider
    from src.supply.cj_transport import CJResearchTransport
    from src.ui.supplier_intelligence import optional_provider_configured

    monkeypatch.setenv("COMMERCE_OFFLINE", "1")
    for name in ("CJ_API_KEY", "OPENAI_API_KEY", "DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD"):
        monkeypatch.setenv(name, "fake-key-must-not-be-used")
    assert not load_settings().api_key
    assert not CJResearchTransport().configured
    assert not DataForSEOTrendProvider().enabled
    assert not optional_provider_configured()
    result = ProductResearchAgent(api_key="fake-key").analyze(product)
    assert result.mode == "demo"


@pytest.mark.parametrize(
    "address,allowed",
    [
        ("127.0.0.1", True),
        ("localhost", True),
        ("::1", True),
        ("0.0.0.0", False),
        ("", False),
        ("192.168.1.5", False),
    ],
)
def test_runtime_refuses_shared_network_binding(address, allowed):
    from src.config import local_binding_allowed

    assert local_binding_allowed(address) is allowed


def test_demand_absolute_deadline_and_body_limit(monkeypatch, product):
    import httpx

    from src.research.providers.demand_trend import DataForSEOTrendProvider

    monkeypatch.setenv("DATAFORSEO_LOGIN", "fixture")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "fixture")
    elapsed = [0]

    class SlowBody(httpx.SyncByteStream):
        def __iter__(self):
            elapsed[0] += 11
            yield b"{"
            elapsed[0] += 11
            yield b"}"

    provider = DataForSEOTrendProvider(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=SlowBody())),
        monotonic=lambda: elapsed[0],
    )
    result = provider.collect(product)
    assert result.status == "failed" and result.failure_kind == "TIMEOUT"
    assert provider.request_count == 1
    provider = DataForSEOTrendProvider(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 1))
        )
    )
    result = provider.collect(product)
    assert result.status == "failed" and result.failure_kind == "INVALID_RESPONSE"
    assert provider.request_count == 1


def test_v5_activation_backs_up_schema4_and_old_reader_rejects_new_version(tmp_path, product):
    from src.database.maintenance import restore_database
    from src.database.supply_repository import SupplyRepository
    from src.discovery.repository import DiscoveryRepository

    repo = ProductRepository(tmp_path / "upgrade.db")
    ext = SupplyRepository(repo, backup_dir=tmp_path / "b4")
    ext.enable()
    from src.agents.product_research_agent import ProductResearchAgent

    repo.save(ProductResearchAgent(force_demo=True).analyze(product))
    before = repo.path.read_bytes()
    storage = DiscoveryRepository(repo, backup_dir=tmp_path / "b5")
    assert storage.list_groups() == []
    assert repo.path.read_bytes() == before
    storage.put("queries", "a", {"query": "reviewed"})
    with repo._connection() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 5
    backups = list((tmp_path / "b5").glob("*.db"))
    assert len(backups) == 1
    restored = tmp_path / "rollback.db"
    restore_database(backups[0], restored)
    with sqlite3.connect(restored) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
    assert len(ProductRepository(restored).list_saved()) == 1
    assert len(ProductRepository(repo.path).list_saved()) == 1
