"""Additive, explicit V3 storage; legacy snapshots and financial assumptions stay intact."""

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ValidationError

from src.config import PROJECT_ROOT
from src.database.database import DataStoreError, ProductRepository
from src.research.models import utc_now
from src.research.telemetry import RunTelemetry

TABLES = (
    "market_reports",
    "page_verifications",
    "demand_observations",
    "market_price_observations",
    "market_economics",
    "provider_cache",
)


class CacheEntry(BaseModel):
    payload: dict
    collected_at: datetime


class MarketIntelligenceRepository:
    def __init__(self, repository: ProductRepository, backup_dir: Path | None = None):
        self.repository = repository
        self.path = repository.path
        self.backup_dir = backup_dir or PROJECT_ROOT / "artifacts" / "v3-backups"

    def _exists(self, table: str) -> bool:
        with self.repository._connection() as conn:
            return (
                conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone()
                is not None
            )

    def enable(self) -> None:
        with self.repository._connection() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 3:
            return
        if version > 3:
            raise DataStoreError("This database needs a newer app version.")
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        identity = hashlib.sha256(str(self.path.resolve()).encode()).hexdigest()[:12]
        backup = self.backup_dir / f"{identity}-before-v3-{utc_now():%Y%m%dT%H%M%S%f}.db"
        try:
            with sqlite3.connect(self.path) as source, sqlite3.connect(backup) as dest:
                source.backup(dest)
        except sqlite3.Error:
            raise DataStoreError(
                "Cannot create pre-V3 database backup; migration stopped."
            ) from None
        with self.repository._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            for table in TABLES:
                conn.execute(
                    f"CREATE TABLE IF NOT EXISTS {table} "
                    "(record_key TEXT PRIMARY KEY, product_id TEXT NOT NULL, "
                    "payload TEXT NOT NULL, collected_at TEXT NOT NULL)"
                )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS provider_attempts "
                "(run_id TEXT PRIMARY KEY, product_id TEXT NOT NULL,"
                "payload TEXT NOT NULL, collected_at TEXT NOT NULL)"
            )
            conn.execute("PRAGMA user_version=3")

    def _get(self, table: str, key: str):
        if not self._exists(table):
            return None
        with self.repository._connection() as conn:
            row = conn.execute(
                f"SELECT payload,collected_at FROM {table} WHERE record_key=?", (key,)
            ).fetchone()
        if row is None:
            return None
        try:
            return CacheEntry(payload=json.loads(row[0]), collected_at=row[1])
        except (ValueError, ValidationError):
            raise DataStoreError("Stored V3 data is invalid. Restore a matching backup.") from None

    @staticmethod
    def _put(conn, table, key, product_id, payload, timestamp):
        conn.execute(
            f"INSERT INTO {table}(record_key,product_id,payload,collected_at) "
            "VALUES(?,?,?,?) ON CONFLICT(record_key) DO UPDATE SET "
            "product_id=excluded.product_id,payload=excluded.payload,"
            "collected_at=excluded.collected_at",
            (key, product_id, json.dumps(payload), timestamp.isoformat()),
        )

    def get_cache(self, key: str) -> CacheEntry | None:
        return self._get("provider_cache", key)

    def save_cache(self, key: str, payload: dict, collected_at: datetime) -> None:
        self.enable()
        with self.repository._connection() as conn:
            self._put(conn, "provider_cache", key, "", payload, collected_at)

    def get_report(self, product_id: str):
        entry = self._get("market_reports", product_id)
        if entry is None:
            return None
        from src.research.market_models import MarketIntelligenceReport

        try:
            return MarketIntelligenceReport.model_validate(entry.payload)
        except ValidationError:
            raise DataStoreError("Stored market report is invalid. Restore a backup.") from None

    def save_report(self, report) -> None:
        self.enable()
        with self.repository._connection() as conn:
            self._put(
                conn,
                "market_reports",
                report.product_id,
                report.product_id,
                report.model_dump(mode="json"),
                report.researched_at,
            )
            # Component records are idempotent observation snapshots, never full HTML.
            for table, values in (
                ("page_verifications", report.page_verifications),
                ("demand_observations", report.demand.observations),
                ("market_price_observations", report.price_observations),
            ):
                for value in values:
                    payload = value.model_dump(mode="json")
                    fields = {
                        "page_verifications": ("source_id", "canonical_url"),
                        "demand_observations": (
                            "provider",
                            "query",
                            "location",
                            "unit",
                            "series_id",
                            "period_start",
                            "period_end",
                        ),
                        "market_price_observations": (
                            "url",
                            "currency",
                            "variant",
                            "brand",
                            "product_name",
                        ),
                    }[table]
                    identity = {field: payload.get(field) for field in fields}
                    stable = json.dumps(identity, sort_keys=True)
                    key = hashlib.sha256(
                        (report.product_id + report.input_fingerprint + stable).encode()
                    ).hexdigest()
                    self._put(conn, table, key, report.product_id, payload, report.researched_at)

    def get_economics(self, product_id: str):
        entry = self._get("market_economics", product_id)
        if entry is None:
            return None
        from src.services.market_economics import MarketEconomicsInputs

        try:
            return MarketEconomicsInputs.model_validate(entry.payload)
        except ValidationError:
            raise DataStoreError("Stored V3 economics is invalid. Restore a backup.") from None

    def save_economics(self, product_id: str, inputs) -> None:
        self.enable()
        with self.repository._connection() as conn:
            self._put(
                conn,
                "market_economics",
                product_id,
                product_id,
                inputs.model_dump(mode="json"),
                utc_now(),
            )

    def save_run(self, product_id: str, run: RunTelemetry) -> None:
        self.enable()
        with self.repository._connection() as conn:
            old = conn.execute(
                "SELECT product_id,payload FROM provider_attempts WHERE run_id=?", (run.run_id,)
            ).fetchone()
            if old and (old[0] != product_id or old[1] != run.model_dump_json()):
                raise DataStoreError("Completed research-run telemetry is immutable.")
            conn.execute(
                "INSERT INTO provider_attempts(run_id,product_id,payload,collected_at) "
                "VALUES(?,?,?,?) ON CONFLICT(run_id) DO NOTHING",
                (run.run_id, product_id, run.model_dump_json(), run.started_at.isoformat()),
            )

    def latest_run(self, product_id: str) -> RunTelemetry | None:
        if not self._exists("provider_attempts"):
            return None
        with self.repository._connection() as conn:
            row = conn.execute(
                "SELECT payload FROM provider_attempts WHERE product_id=? "
                "ORDER BY collected_at DESC LIMIT 1",
                (product_id,),
            ).fetchone()
        try:
            return RunTelemetry.model_validate_json(row[0]) if row else None
        except ValidationError:
            raise DataStoreError(
                "Stored research telemetry is invalid. Restore a backup."
            ) from None
