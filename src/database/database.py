"""Small SQLite repository storing validated, versioned JSON snapshots."""

import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Iterator

from pydantic import ValidationError

from src.schemas.product import Product, ResearchResult


class DataStoreError(RuntimeError):
    """A storage error safe for the UI to display."""


class ProductRepository:
    def __init__(self, path: Path):
        self.path = Path(path)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._connection() as conn:
                conn.execute("""CREATE TABLE IF NOT EXISTS saved_products (
                    product_id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                    schema_version INTEGER NOT NULL DEFAULT 1,
                    saved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
                conn.execute("""CREATE TABLE IF NOT EXISTS candidates (
                    product_id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                    schema_version INTEGER NOT NULL DEFAULT 1)""")
        except OSError as exc:
            raise DataStoreError("Cannot create the database folder. Check DATABASE_PATH.") from exc

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        try:
            with closing(sqlite3.connect(self.path, timeout=10)) as conn, conn:
                yield conn
        except sqlite3.Error as exc:
            raise DataStoreError(
                "Cannot access the local database. Check its path and permissions."
            ) from exc

    def save(self, result: ResearchResult) -> bool:
        """Create or update one snapshot. Return True only for a new saved entry."""
        payload = result.model_dump_json()
        with self._connection() as conn:
            cursor = conn.execute(
                "INSERT INTO saved_products (product_id, payload) VALUES (?, ?) "
                "ON CONFLICT(product_id) DO NOTHING",
                (result.product.id, payload),
            )
            created = cursor.rowcount == 1
            if not created:
                conn.execute(
                    "UPDATE saved_products SET payload=?, saved_at=CURRENT_TIMESTAMP "
                    "WHERE product_id=?",
                    (payload, result.product.id),
                )
        return created

    def list_saved(self) -> list[ResearchResult]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT payload FROM saved_products ORDER BY saved_at DESC, product_id"
            ).fetchall()
        try:
            return [ResearchResult.model_validate_json(row[0]) for row in rows]
        except ValidationError as exc:
            raise DataStoreError(
                "A saved analysis is invalid. Restore the database from a backup."
            ) from exc

    def remove_saved(self, product_id: str) -> bool:
        with self._connection() as conn:
            return (
                conn.execute(
                    "DELETE FROM saved_products WHERE product_id=?", (product_id,)
                ).rowcount
                == 1
            )

    def add_candidate(self, product: Product) -> None:
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO candidates (product_id, payload) VALUES (?, ?) "
                "ON CONFLICT(product_id) DO UPDATE SET payload=excluded.payload",
                (product.id, product.model_dump_json()),
            )

    def list_candidates(self) -> list[Product]:
        with self._connection() as conn:
            rows = conn.execute("SELECT payload FROM candidates ORDER BY product_id").fetchall()
        try:
            return [Product.model_validate_json(row[0]) for row in rows]
        except ValidationError as exc:
            raise DataStoreError(
                "A manual product is invalid. Restore the database from a backup."
            ) from exc
