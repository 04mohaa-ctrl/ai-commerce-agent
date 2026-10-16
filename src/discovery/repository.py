"""Additive local records; reading never migrates or changes V4 user_version."""

import json
from pathlib import Path
from uuid import uuid4

from src.discovery.models import CatalogItem


class DiscoveryRepository:
    def __init__(self, repo, backup_dir=None):
        self.repo = repo
        from src.config import PROJECT_ROOT

        self.backup_dir = Path(backup_dir or PROJECT_ROOT / "artifacts" / "v5-backups")

    def get(self, kind, key):
        with self.repo._connection() as conn:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='workspace_v5'"
            ).fetchone()
            if not exists:
                return None
            row = conn.execute(
                "SELECT payload FROM workspace_v5 WHERE kind=? AND record_key=?", (kind, key)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, kind, key, payload):
        self.enable()
        with self.repo._connection() as conn:
            conn.execute(
                "INSERT INTO workspace_v5 VALUES(?,?,?) ON CONFLICT(kind,record_key) "
                "DO UPDATE SET payload=excluded.payload",
                (kind, key, json.dumps(payload, ensure_ascii=False)),
            )

    @staticmethod
    def create_table(conn):
        conn.execute(
            "CREATE TABLE IF NOT EXISTS workspace_v5 (kind TEXT NOT NULL, "
            "record_key TEXT NOT NULL, payload TEXT NOT NULL, "
            "PRIMARY KEY(kind,record_key))"
        )

    def enable(self):
        from src.database.database import DataStoreError
        from src.database.maintenance import backup_database
        from src.database.supply_repository import SupplyRepository

        with self.repo._connection() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 5:
            return
        SupplyRepository(self.repo).enable()
        with self.repo._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            # Serialize the snapshot and migration, including across app sessions.
            if conn.execute("PRAGMA user_version").fetchone()[0] == 5:
                return
            try:
                self.backup_dir.mkdir(parents=True, exist_ok=True)
                backup_database(
                    self.repo.path,
                    self.backup_dir / f"before-v5-{uuid4().hex[:12]}.db",
                    expected_version=4,
                )
            except (OSError, ValueError):
                raise DataStoreError("Cannot verify pre-V5 backup; activation stopped.") from None
            self.create_table(conn)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS workspace_meta_v5 (version INTEGER PRIMARY KEY)"
            )
            conn.execute("INSERT OR IGNORE INTO workspace_meta_v5 VALUES(5)")
            conn.execute("PRAGMA user_version=5")

    def get_origin(self, product_id):
        payload = self.get("origin", product_id)
        return CatalogItem.model_validate(payload) if payload else None

    def list_groups(self):
        with self.repo._connection() as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='workspace_v5'").fetchone():
                return []
            rows = conn.execute(
                "SELECT payload FROM workspace_v5 WHERE kind='group' ORDER BY record_key"
            ).fetchall()
        return [json.loads(row[0]) for row in rows]
