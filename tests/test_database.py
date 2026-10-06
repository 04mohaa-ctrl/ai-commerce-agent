import sqlite3

import pytest


def test_saved_analysis_persists_with_complete_snapshot_after_reopen(tmp_path, result):
    from src.database.database import ProductRepository

    path = tmp_path / "nested" / "research.db"
    assert ProductRepository(path).save(result) is True
    saved = ProductRepository(path).list_saved()
    assert len(saved) == 1
    assert saved[0] == result


def test_repeated_save_updates_one_row_and_canonical_identity(tmp_path, result):
    from src.database.database import ProductRepository

    repo = ProductRepository(tmp_path / "research.db")
    assert repo.save(result) is True
    updated = result.model_copy(update={"notice": "updated snapshot"})
    updated.product = result.product.model_copy(update={"name": "pet hair remover"})
    assert repo.save(updated) is False
    rows = repo.list_saved()
    assert len(rows) == 1
    assert rows[0].notice == "updated snapshot"


def test_remove_saved_product_is_durable_and_idempotent(tmp_path, result):
    from src.database.database import ProductRepository

    path = tmp_path / "research.db"
    repo = ProductRepository(path)
    repo.save(result)
    assert repo.remove_saved(result.product.id) is True
    assert repo.remove_saved(result.product.id) is False
    assert ProductRepository(path).list_saved() == []


def test_manual_candidates_persist_and_update_without_duplicates(tmp_path, product):
    from src.database.database import ProductRepository

    path = tmp_path / "research.db"
    repo = ProductRepository(path)
    repo.add_candidate(product)
    repo.add_candidate(product.model_copy(update={"cost": 7}))
    rows = ProductRepository(path).list_candidates()
    assert len(rows) == 1
    assert rows[0].cost == 7


def test_corrupt_database_and_invalid_snapshot_have_controlled_errors(tmp_path, result):
    from src.database.database import DataStoreError, ProductRepository

    bad_path = tmp_path / "bad.db"
    bad_path.write_text("not a sqlite database")
    with pytest.raises(DataStoreError):
        ProductRepository(bad_path)
    path = tmp_path / "valid.db"
    repo = ProductRepository(path)
    repo.save(result)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE saved_products SET payload = '{}' ")
    with pytest.raises(DataStoreError):
        repo.list_saved()
