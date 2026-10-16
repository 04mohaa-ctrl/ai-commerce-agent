"""Explicit V4 storage: immutable history, transactional current views and local choices."""

import hashlib
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from src.config import PROJECT_ROOT
from src.database.database import DataStoreError
from src.database.market_repository import MarketIntelligenceRepository
from src.research.models import utc_now


class SupplyRepository:
    def __init__(self, repository, backup_dir=None):
        self.repository = repository
        self.path = repository.path
        self.backup_dir = Path(backup_dir or PROJECT_ROOT / "artifacts" / "v4-backups")

    def _exists(self):
        with self.repository._connection() as conn:
            return bool(
                conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='supply_v4_meta' AND type='table'"
                ).fetchone()
            )

    def _backup(self):
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        while True:
            # Short paths also keep Windows SQLite usable inside isolated test directories.
            target = self.backup_dir / f"v4-{uuid4().hex[:12]}.db"
            try:
                descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                continue
            os.close(descriptor)
            break
        # SQLite backup includes committed WAL state consistently.
        with (
            closing(sqlite3.connect(self.path)) as source,
            closing(sqlite3.connect(target)) as dest,
        ):
            source.backup(dest)
            if (
                dest.execute("PRAGMA user_version").fetchone()[0] != 3
                or dest.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
            ):
                raise DataStoreError("Pre-V4 backup could not be verified; activation stopped.")

    def enable(self):
        if self._exists():
            return
        MarketIntelligenceRepository(self.repository).enable()
        with self.repository._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='supply_v4_meta'"
            ).fetchone():
                return
            try:
                self._backup()
            except (OSError, sqlite3.Error):
                raise DataStoreError("Cannot create pre-V4 backup; activation stopped.") from None
            conn.execute("CREATE TABLE IF NOT EXISTS supply_v4_meta (version INTEGER PRIMARY KEY)")
            conn.execute("INSERT OR IGNORE INTO supply_v4_meta VALUES(4)")
            for table in ("current", "settings", "selection", "financial", "shortlist", "cache"):
                conn.execute(
                    f"CREATE TABLE IF NOT EXISTS supply_v4_{table} "
                    "(record_key TEXT PRIMARY KEY, product_id TEXT NOT NULL, payload TEXT NOT NULL)"
                )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS supply_v4_history "
                "(record_key TEXT PRIMARY KEY, product_id TEXT NOT NULL, "
                "kind TEXT NOT NULL, payload TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS supply_v4_actions "
                "(action_id TEXT PRIMARY KEY, product_id TEXT NOT NULL, "
                "started_at TEXT NOT NULL, payload TEXT)"
            )
            conn.execute("PRAGMA user_version=4")

    def _get(self, table, key):
        if not self._exists():
            return None
        with self.repository._connection() as conn:
            row = conn.execute(
                f"SELECT payload FROM supply_v4_{table} WHERE record_key=?", (key,)
            ).fetchone()
        try:
            return json.loads(row[0]) if row else None
        except ValueError:
            raise DataStoreError(
                "Stored V4 data is invalid; restore its matching backup."
            ) from None

    @staticmethod
    def _put(conn, table, key, product_id, payload):
        conn.execute(
            f"INSERT INTO supply_v4_{table} VALUES(?,?,?) ON CONFLICT(record_key) "
            "DO UPDATE SET product_id=excluded.product_id,payload=excluded.payload",
            (key, product_id, json.dumps(payload, sort_keys=True)),
        )

    @staticmethod
    def _history(conn, key, product_id, kind, payload):
        serialized = json.dumps(payload, sort_keys=True)
        old = conn.execute(
            "SELECT payload FROM supply_v4_history WHERE record_key=?", (key,)
        ).fetchone()
        if old and old[0] != serialized:
            raise DataStoreError("V4 observation history is immutable.")
        conn.execute(
            "INSERT OR IGNORE INTO supply_v4_history VALUES(?,?,?,?)",
            (key, product_id, kind, serialized),
        )

    def _save(self, table, key, product_id, value):
        self.enable()
        payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
        with self.repository._connection() as conn:
            self._put(conn, table, key, product_id, payload)

    def _model(self, table, key, model):
        payload = self._get(table, key)
        try:
            return model.model_validate(payload) if payload is not None else None
        except ValidationError:
            raise DataStoreError(
                "Stored V4 record is invalid; restore a matching backup."
            ) from None

    def get_settings(self, product_id):
        from src.supply.models import Destination

        return self._model("settings", product_id, Destination)

    def save_settings(self, product_id, destination):
        self._save("settings", product_id, product_id, destination)

    def get_requirements(self, product_id):
        from src.supply.models import SupplierRequirements

        return self._model("settings", "requirements:" + product_id, SupplierRequirements) or (
            SupplierRequirements()
        )

    def save_requirements(self, product_id, requirements):
        self._save("settings", "requirements:" + product_id, product_id, requirements)

    def get_report(self, product_id):
        from src.supply.models import SupplyIntelligenceReport

        return self._model("current", product_id, SupplyIntelligenceReport)

    def save_report(self, report):
        self.enable()
        with self.repository._connection() as conn:
            for offer in report.offers:
                for kind, value in (
                    ("candidate", offer.candidate),
                    ("variant", offer.variant),
                    ("stock", offer.stock),
                    ("shipping", offer.quote),
                ):
                    if value is not None:
                        self._history(
                            conn, value.id, report.product_id, kind, value.model_dump(mode="json")
                        )
            self._put(
                conn,
                "current",
                report.product_id,
                report.product_id,
                report.model_dump(mode="json"),
            )

    def get_selection(self, product_id):
        from src.supply.models import SupplierSelection

        return self._model("selection", product_id, SupplierSelection)

    def save_selection(self, product_id, selection):
        if selection is not None:
            self._save("selection", product_id, product_id, selection)
        elif self._exists():
            with self.repository._connection() as conn:
                conn.execute("DELETE FROM supply_v4_selection WHERE record_key=?", (product_id,))

    def get_financial(self, product_id):
        from src.supply.economics import FinancialSnapshot

        return self._model("financial", product_id, FinancialSnapshot)

    def save_financial(self, product_id, snapshot):
        self.enable()
        payload = snapshot.model_dump(mode="json")
        key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        with self.repository._connection() as conn:
            self._history(conn, key, product_id, "financial", payload)
            self._put(conn, "financial", product_id, product_id, payload)

    def save_shortlist(self, product_id, offer, label, notes=""):
        if label not in {"Preferred", "Backup"} or len(notes) > 1000:
            raise ValueError("Use Preferred/Backup and notes of at most1000characters.")
        key = hashlib.sha256((product_id + offer.id).encode()).hexdigest()
        self._save(
            "shortlist",
            key,
            product_id,
            {
                "offer": offer.model_dump(mode="json"),
                "label": label,
                "notes": notes,
                "saved_at": utc_now().isoformat(),
            },
        )

    def get_shortlist(self, product_id):
        if not self._exists():
            return []
        with self.repository._connection() as conn:
            rows = conn.execute(
                "SELECT payload FROM supply_v4_shortlist WHERE product_id=?", (product_id,)
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def get_cache(self, key):
        from src.supply.models import ProviderOutcome

        return self._model("cache", key, ProviderOutcome)

    def save_cache(self, key, outcome):
        self._save("cache", key, "", outcome)

    def claim_action(self, action_id, product_id=""):
        self.enable()
        with self.repository._connection() as conn:
            return (
                conn.execute(
                    "INSERT OR IGNORE INTO supply_v4_actions VALUES(?,?,?,NULL)",
                    (action_id, product_id, utc_now().isoformat()),
                ).rowcount
                == 1
            )

    def save_action(self, product_id, telemetry):
        self.enable()
        payload = telemetry.model_dump_json()
        with self.repository._connection() as conn:
            old = conn.execute(
                "SELECT product_id,payload FROM supply_v4_actions WHERE action_id=?",
                (telemetry.action_id,),
            ).fetchone()
            if old and (old[0] != product_id or (old[1] is not None and old[1] != payload)):
                raise DataStoreError("Completed V4 action telemetry is immutable.")
            conn.execute(
                "INSERT INTO supply_v4_actions VALUES(?,?,?,?) ON CONFLICT(action_id) "
                "DO UPDATE SET payload=excluded.payload,product_id=excluded.product_id",
                (telemetry.action_id, product_id, telemetry.started_at.isoformat(), payload),
            )

    def get_latest_action(self, product_id):
        from src.supply.models import ActionTelemetry

        if not self._exists():
            return None
        with self.repository._connection() as conn:
            row = conn.execute(
                "SELECT payload FROM supply_v4_actions WHERE product_id=? AND payload IS NOT NULL "
                "ORDER BY started_at DESC LIMIT 1",
                (product_id,),
            ).fetchone()
        return ActionTelemetry.model_validate_json(row[0]) if row else None
