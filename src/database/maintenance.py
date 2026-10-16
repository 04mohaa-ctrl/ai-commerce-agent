"""Local operator recovery and retention tools. No provider or credential access."""

import argparse
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from src.database.database import ProductRepository


def _readonly(path):
    path = Path(path).resolve(strict=True)
    return sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)


def backup_database(source, target, *, expected_version=None):
    """Consistent SQLite snapshot including committed WAL; never overwrite a file."""
    target = Path(target)
    with closing(_readonly(source)) as src:
        if src.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Source database failed integrity verification.")
        # Reserve destination only after validating source. Explicitly reject existing paths.
        descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        try:
            with closing(sqlite3.connect(target)) as dest:
                src.backup(dest)
                if dest.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Backup failed integrity verification.")
                if expected_version is not None and (
                    dest.execute("PRAGMA user_version").fetchone()[0] != expected_version
                ):
                    raise ValueError("Backup schema differs from expected rollback version.")
        except Exception:
            target.unlink(missing_ok=True)
            raise
    return target


def restore_database(source, target):
    """Restore to a NEW path; caller verifies it before choosing DATABASE_PATH."""
    return backup_database(source, target)


def export_database(repo):
    with repo._connection() as conn:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            )
        ]
        exported = {}
        for table in tables:
            # Names come solely from sqlite_master and are escaped as identifiers.
            quoted = '"' + table.replace('"', '""') + '"'
            cursor = conn.execute(f"SELECT * FROM {quoted}")
            columns = [field[0] for field in cursor.description]
            exported[table] = [dict(zip(columns, row, strict=True)) for row in cursor]
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    return {
        "schema": "ai-commerce-local-export-1",
        "database_version": version,
        "scope": "Entire single-operator database, including histories and caches",
        "tables": exported,
    }


def delete_product(repo, product_id):
    """Explicit local purge. Shared caches are cleared to avoid retained references."""
    with repo._connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        for table in sorted(tables):
            quoted = '"' + table.replace('"', '""') + '"'
            columns = {row[1] for row in conn.execute(f"PRAGMA table_info({quoted})")}
            if "product_id" in columns:
                conn.execute(f"DELETE FROM {quoted} WHERE product_id=?", (product_id,))
            # Cache entries may contain a product only in JSON. Purge shared caches,
            # not observations for unrelated products.
            if "cache" in table:
                conn.execute(f"DELETE FROM {quoted}")
        if "workspace_v5" in tables:
            rows = conn.execute("SELECT kind,record_key,payload FROM workspace_v5").fetchall()
            for kind, key, payload in rows:
                if product_id in key or product_id in payload or kind == "search":
                    conn.execute(
                        "DELETE FROM workspace_v5 WHERE kind=? AND record_key=?", (kind, key)
                    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["backup", "restore", "export", "delete-product"])
    parser.add_argument("database", type=Path)
    parser.add_argument("target", help="New file path, or exact product ID for deletion")
    parser.add_argument("--backup", type=Path, help="Required new backup path before deletion")
    args = parser.parse_args()
    try:
        if args.action in {"backup", "restore"}:
            backup_database(args.database, args.target)
        elif args.action == "export":
            with open(args.target, "x", encoding="utf-8") as output:
                json.dump(
                    export_database(ProductRepository(args.database)),
                    output,
                    indent=2,
                    ensure_ascii=False,
                )
        else:
            if not args.backup:
                parser.error("delete-product requires --backup to a new file")
            backup_database(args.database, args.backup)
            delete_product(ProductRepository(args.database), args.target)
        print("Local operation completed. No provider requests.")
    except (OSError, ValueError, sqlite3.Error):
        parser.exit(
            1,
            "Operation failed; verify paths and database integrity. No source file overwritten.\n",
        )


if __name__ == "__main__":
    main()
