import sqlite3

import pytest

from src.database.database import DataStoreError, ProductRepository
from src.database.market_repository import MarketIntelligenceRepository
from src.database.supply_repository import SupplyRepository


def setup(tmp_path):
    legacy = ProductRepository(tmp_path / "supply.db")
    MarketIntelligenceRepository(legacy, backup_dir=tmp_path / "v3-backups").enable()
    return legacy, SupplyRepository(legacy, backup_dir=tmp_path / "v4-backups")


def test_reads_do_not_activate_v4_and_backup_is_schema3(tmp_path, result):
    legacy, supply = setup(tmp_path)
    legacy.save(result)
    with sqlite3.connect(legacy.path) as conn:
        original = conn.execute("SELECT payload FROM saved_products").fetchone()[0]
        conn.execute("PRAGMA journal_mode=WAL")
    assert supply.get_settings(result.product.id) is None
    assert supply.get_report(result.product.id) is None
    with sqlite3.connect(legacy.path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    supply.enable()
    supply.enable()
    backups = list((tmp_path / "v4-backups").glob("*.db"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT payload FROM saved_products").fetchone()[0] == original
    reopened = ProductRepository(legacy.path)
    MarketIntelligenceRepository(reopened).enable()
    assert reopened.list_saved() == [result]
    with sqlite3.connect(legacy.path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
        assert conn.execute("SELECT payload FROM saved_products").fetchone()[0] == original


def test_settings_actions_restart_and_idempotence(tmp_path):
    from src.supply.models import ActionTelemetry, Destination

    legacy, supply = setup(tmp_path)
    supply.save_settings("p", Destination(country="SE", quantity=2))
    run = ActionTelemetry(action="supplier")
    assert supply.claim_action(run.action_id, "p")
    assert not supply.claim_action(run.action_id, "p")
    supply.save_action("p", run)
    supply.save_action("p", run)
    fresh = SupplyRepository(ProductRepository(legacy.path))
    assert fresh.get_settings("p").country == "SE"
    assert fresh.get_settings("p").quantity == 2
    assert fresh.get_latest_action("p").action_id == run.action_id
    changed = run.model_copy(update={"requests": {"search": 9}})
    with pytest.raises(DataStoreError):
        fresh.save_action("p", changed)


def test_backup_failure_leaves_schema3_untouched(tmp_path, monkeypatch):
    legacy, supply = setup(tmp_path)

    def fail(*args, **kwargs):
        raise OSError("Cannot write backup")

    monkeypatch.setattr(supply, "_backup", fail)
    with pytest.raises(DataStoreError):
        supply.enable()
    with sqlite3.connect(legacy.path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        assert not conn.execute(
            "SELECT name FROM sqlite_master WHERE name='supply_v4_meta'"
        ).fetchone()


def test_completed_action_cannot_move_to_another_product(tmp_path):
    from src.supply.models import ActionTelemetry

    _, supply = setup(tmp_path)
    run = ActionTelemetry(action="supplier")
    supply.save_action("original-product", run)
    with pytest.raises(DataStoreError):
        supply.save_action("different-product", run)
    assert supply.get_latest_action("original-product").action_id == run.action_id
    assert supply.get_latest_action("different-product") is None


def test_partial_schema4_marker_is_rejected_without_downgrade(tmp_path):
    path = tmp_path / "invalid.db"
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version=4")
        conn.execute("CREATE TABLE supply_v4_meta(version INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO supply_v4_meta VALUES(4)")
    with pytest.raises(DataStoreError):
        ProductRepository(path)


def test_report_transaction_rolls_back_history_and_current_together(tmp_path, product, monkeypatch):
    from src.supply.models import Destination
    from src.supply.service import SupplierIntelligenceService
    from tests.test_supply_pipeline import FixtureSupplier

    legacy, supply = setup(tmp_path)
    service = SupplierIntelligenceService(supply, FixtureSupplier(product))
    first = service.research(product, Destination())
    with legacy._connection() as conn:
        history = conn.execute("SELECT * FROM supply_v4_history ORDER BY record_key").fetchall()
    original = supply._history
    calls = []

    def fail_second(conn, *args):
        calls.append(1)
        if len(calls) == 2:
            raise DataStoreError("Injected transactional failure")
        return original(conn, *args)

    monkeypatch.setattr(supply, "_history", fail_second)
    changed = first.model_copy(deep=True)
    changed.offers = [
        first.offers[0].model_copy(
            update={
                "candidate": first.offers[0].candidate.model_copy(
                    update={"name": "Updated candidate"}
                )
            }
        )
    ]
    with pytest.raises(DataStoreError):
        supply.save_report(changed)
    assert supply.get_report(product.id).model_dump() == first.model_dump()
    with legacy._connection() as conn:
        assert (
            conn.execute("SELECT * FROM supply_v4_history ORDER BY record_key").fetchall()
            == history
        )


def test_selection_shortlist_and_revision_survive_restart(tmp_path, product):
    from src.supply.economics import FinancialSnapshot
    from src.supply.models import Destination, SupplierSelection
    from src.supply.service import SupplierIntelligenceService
    from tests.test_supply_pipeline import FixtureSupplier

    legacy, supply = setup(tmp_path)
    report = SupplierIntelligenceService(supply, FixtureSupplier(product)).research(
        product, Destination()
    )
    selection = SupplierSelection(offer=report.offers[0])
    supply.save_selection(product.id, selection)
    supply.save_shortlist(product.id, selection.offer, "Backup", "Review warehouse")
    finance = FinancialSnapshot()
    supply.save_financial(product.id, finance)
    reopened = SupplyRepository(ProductRepository(legacy.path))
    assert reopened.get_selection(product.id).id == selection.id
    assert reopened.get_shortlist(product.id)[0]["notes"] == "Review warehouse"
    assert reopened.get_financial(product.id).model_dump() == finance.model_dump()
    assert reopened.get_report(product.id).offers[0].id == selection.offer.id


def test_backup_never_overwrites_a_previous_backup_at_same_timestamp(tmp_path, monkeypatch):
    from src.research.models import utc_now

    _, supply = setup(tmp_path)
    fixed = utc_now()
    monkeypatch.setattr("src.database.supply_repository.utc_now", lambda: fixed)
    supply._backup()
    first = next((tmp_path / "v4-backups").glob("*.db"))
    original = first.read_bytes()
    supply._backup()
    assert len(list((tmp_path / "v4-backups").glob("*.db"))) == 2
    assert first.read_bytes() == original


def test_shortlist_keeps_distinct_shipping_methods(tmp_path, product):
    from src.supply.models import Destination, ShippingQuote
    from src.supply.service import SupplierIntelligenceService
    from tests.test_supply_pipeline import FixtureSupplier

    _, supply = setup(tmp_path)
    provider = FixtureSupplier(product)
    offer = SupplierIntelligenceService(supply, provider).research(product, Destination()).offers[0]
    quote = ShippingQuote.model_validate(
        provider.shipping(offer.variant, offer.stock, Destination()).records[0]
    )
    first = offer.model_copy(update={"quote": quote})
    second = offer.model_copy(update={"quote": quote.model_copy(update={"method": "Other method"})})
    supply.save_shortlist(product.id, first, "Preferred")
    supply.save_shortlist(product.id, second, "Backup")
    assert len(supply.get_shortlist(product.id)) == 2
