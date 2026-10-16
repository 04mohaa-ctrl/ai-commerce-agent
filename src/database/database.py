"""Small SQLite repository storing validated, versioned JSON snapshots."""

import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Iterator

from pydantic import ValidationError

from src.research.models import ResearchAttempt, ResearchReport
from src.research.scoring import confidence_for
from src.schemas.product import Product, ResearchResult
from src.services.economics import EconomicsInputs


class DataStoreError(RuntimeError):
    """A storage error safe for the UI to display."""


class ProductRepository:
    def __init__(self, path: Path):
        self.path = Path(path)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                version = conn.execute("PRAGMA user_version").fetchone()[0]
                tables = (
                    {
                        row[0]
                        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                    }
                    if version in {4, 5}
                    else set()
                )
                required_v4 = {
                    f"supply_v4_{name}"
                    for name in (
                        "meta",
                        "current",
                        "settings",
                        "selection",
                        "financial",
                        "shortlist",
                        "cache",
                        "history",
                        "actions",
                    )
                }
                valid_v4 = (
                    version in {4, 5}
                    and required_v4 <= tables
                    and conn.execute("SELECT 1 FROM supply_v4_meta WHERE version=4").fetchone()
                )
                valid_v5 = (
                    version == 5
                    and valid_v4
                    and {"workspace_v5", "workspace_meta_v5"} <= tables
                    and conn.execute("SELECT 1 FROM workspace_meta_v5 WHERE version=5").fetchone()
                )
                if version > 3 and not (valid_v4 and version == 4 or valid_v5):
                    raise DataStoreError(
                        "This database needs a newer app version. No migration performed."
                    )
                conn.execute("""CREATE TABLE IF NOT EXISTS saved_products (
                    product_id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                    schema_version INTEGER NOT NULL DEFAULT 1,
                    saved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
                conn.execute("""CREATE TABLE IF NOT EXISTS candidates (
                    product_id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                    schema_version INTEGER NOT NULL DEFAULT 1)""")
                if version < 2:
                    conn.execute("""CREATE TABLE IF NOT EXISTS research_records (
                        product_id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                        schema_version INTEGER NOT NULL DEFAULT 2)""")
                    conn.execute("""CREATE TABLE IF NOT EXISTS research_sources (
                        product_id TEXT NOT NULL, source_id TEXT NOT NULL, url TEXT NOT NULL,
                        payload TEXT NOT NULL, PRIMARY KEY(product_id, source_id),
                        UNIQUE(product_id, url), FOREIGN KEY(product_id)
                        REFERENCES research_records(product_id) ON DELETE CASCADE)""")
                    conn.execute("""CREATE TABLE IF NOT EXISTS research_attempts (
                        product_id TEXT PRIMARY KEY, payload TEXT NOT NULL)""")
                    conn.execute("""CREATE TABLE IF NOT EXISTS economics (
                        product_id TEXT PRIMARY KEY, payload TEXT NOT NULL)""")
                    conn.execute("PRAGMA user_version=2")
        except OSError as exc:
            raise DataStoreError("Cannot create the database folder. Check DATABASE_PATH.") from exc

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        try:
            with closing(sqlite3.connect(self.path, timeout=10)) as conn, conn:
                conn.execute("PRAGMA foreign_keys=ON")
                yield conn
        except sqlite3.Error as exc:
            raise DataStoreError(
                "Cannot access the local database. Check its path and permissions."
            ) from exc

    def save(self, result: ResearchResult) -> bool:
        """Create or update one snapshot. Return True only for a new saved entry."""
        if result.product.supplier_identity:
            from src.discovery.repository import DiscoveryRepository

            DiscoveryRepository(self).enable()
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
        if product.supplier_identity:
            from src.discovery.repository import DiscoveryRepository

            DiscoveryRepository(self).enable()
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

    def save_research(self, product_id: str, report: ResearchReport) -> None:
        """Upsert one report and its unique sources; never replace usable evidence with failure."""
        normalized = ResearchReport.model_validate(report.model_dump())
        normalized.confidence_level = confidence_for(normalized)
        attempt = ResearchAttempt(
            status=normalized.status,
            attempted_at=normalized.researched_at,
            notice=normalized.notice,
        )
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO research_attempts(product_id,payload) VALUES(?,?) "
                "ON CONFLICT(product_id) DO UPDATE SET payload=excluded.payload",
                (product_id, attempt.model_dump_json()),
            )
            prior = conn.execute(
                "SELECT payload FROM research_records WHERE product_id=?", (product_id,)
            ).fetchone()
            if normalized.status in {"failed", "insufficient"} and prior:
                try:
                    previous = ResearchReport.model_validate_json(prior[0])
                except ValidationError as exc:
                    raise DataStoreError(
                        "Stored research is invalid. Restore a database backup."
                    ) from exc
                comparable = previous.input_fingerprint == normalized.input_fingerprint
                if (
                    comparable
                    and previous.sources
                    and (
                        previous.status == "completed"
                        or not normalized.sources
                        or normalized.status == "failed"
                    )
                ):
                    return
                if normalized.status == "failed" and not normalized.sources and previous.sources:
                    return
            conn.execute(
                "INSERT INTO research_records(product_id,payload) VALUES(?,?) "
                "ON CONFLICT(product_id) DO UPDATE SET payload=excluded.payload",
                (product_id, normalized.model_dump_json()),
            )
            conn.execute("DELETE FROM research_sources WHERE product_id=?", (product_id,))
            conn.executemany(
                "INSERT INTO research_sources(product_id,source_id,url,payload) VALUES(?,?,?,?)",
                [(product_id, s.id, s.url, s.model_dump_json()) for s in normalized.sources],
            )

    def get_research(self, product_id: str) -> ResearchReport | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT payload FROM research_records WHERE product_id=?", (product_id,)
            ).fetchone()
        try:
            return ResearchReport.model_validate_json(row[0]) if row else None
        except ValidationError as exc:
            raise DataStoreError("Stored research is invalid. Restore a database backup.") from exc

    def save_research_attempt(self, product_id: str, attempt: ResearchAttempt) -> None:
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO research_attempts(product_id,payload) VALUES(?,?) "
                "ON CONFLICT(product_id) DO UPDATE SET payload=excluded.payload",
                (product_id, attempt.model_dump_json()),
            )

    def get_research_attempt(self, product_id: str) -> ResearchAttempt | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT payload FROM research_attempts WHERE product_id=?", (product_id,)
            ).fetchone()
        try:
            return ResearchAttempt.model_validate_json(row[0]) if row else None
        except ValidationError as exc:
            raise DataStoreError(
                "Stored research attempt is invalid. Restore a database backup."
            ) from exc

    def save_economics(self, product_id: str, inputs: EconomicsInputs) -> None:
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO economics(product_id,payload) VALUES(?,?) "
                "ON CONFLICT(product_id) DO UPDATE SET payload=excluded.payload",
                (product_id, inputs.model_dump_json()),
            )

    def get_economics(self, product_id: str) -> EconomicsInputs | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT payload FROM economics WHERE product_id=?", (product_id,)
            ).fetchone()
        try:
            return EconomicsInputs.model_validate_json(row[0]) if row else None
        except ValidationError as exc:
            raise DataStoreError(
                "Stored economics inputs are invalid. Restore a database backup."
            ) from exc
