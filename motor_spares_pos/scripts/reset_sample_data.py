"""Development-only reset for local sample data.

This script is intentionally outside the application UI. It never drops tables,
recreates a database, or deletes users, roles, permissions, or normal settings.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = ROOT.parents[1]
LOCAL_DB = (Path.cwd() / "data" / "pos.db" if (Path.cwd() / "data" / "pos.db").exists()
            else WORKSPACE_ROOT / "data" / "pos.db" if (WORKSPACE_ROOT / "data" / "pos.db").exists()
            else ROOT / "data" / "pos.db")
SYNC_DB = ROOT / "server_data" / "sync_server.db"
CONFIRMATION = "RESET SAMPLE DATA"

LOCAL_CLEAR_ORDER = [
    "return_items", "refunds", "sale_items", "payments", "invoices", "returns",
    "stock_movements", "sales", "sync_queue", "sync_log", "audit_logs",
    "products", "customers", "categories", "vehicle_models",
    "product_tombstones",
]
SYNC_CLEAR_ORDER = ["sync_records", "products", "customers"]
PRESERVED_LOCAL = ["users", "roles", "permissions", "user_permissions", "settings"]


def backup_database(path: Path) -> Path:
    if not path.exists():
        raise FileNotFoundError(f"Database does not exist: {path}")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(f"{path.stem}_before_sample_reset_{stamp}{path.suffix}")
    counter = 1
    while backup.exists():
        backup = path.with_name(f"{path.stem}_before_sample_reset_{stamp}_{counter}{path.suffix}")
        counter += 1
    source = sqlite3.connect(path)
    target = sqlite3.connect(backup)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    return backup


def schema_report(path: Path) -> dict:
    conn = sqlite3.connect(path)
    try:
        tables = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )]
        foreign_keys = {
            table: [tuple(row) for row in conn.execute(f'PRAGMA foreign_key_list("{table}")')]
            for table in tables
        }
        counts = {
            table: conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in tables
        }
        return {"tables": tables, "foreign_keys": foreign_keys, "counts": counts}
    finally:
        conn.close()


def clear_local(path: Path) -> dict:
    deleted = {}
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute("BEGIN")
        tables = set(schema_report(path)["tables"])
        trigger_row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' AND name='prevent_product_physical_delete'"
        ).fetchone()
        if trigger_row:
            conn.execute("DROP TRIGGER prevent_product_physical_delete")
        if "returns" in tables and "invoices" in tables:
            conn.execute("UPDATE returns SET original_invoice_id=NULL")
        for table in LOCAL_CLEAR_ORDER:
            if table not in tables:
                continue
            count = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            conn.execute(f'DELETE FROM "{table}"')
            deleted[table] = count
        if "settings" in tables:
            deleted["sync_last_pulled_at"] = conn.execute(
                "DELETE FROM settings WHERE key='sync_last_pulled_at'"
            ).rowcount
        placeholders = ",".join("?" for _ in LOCAL_CLEAR_ORDER)
        conn.execute(f"DELETE FROM sqlite_sequence WHERE name IN ({placeholders})", LOCAL_CLEAR_ORDER)
        if trigger_row:
            conn.execute(trigger_row[0])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return deleted


def clear_sync_server(path: Path) -> dict:
    if not path.exists():
        return {}
    deleted = {}
    conn = sqlite3.connect(path)
    try:
        conn.execute("BEGIN")
        tables = set(schema_report(path)["tables"])
        for table in SYNC_CLEAR_ORDER:
            if table not in tables:
                continue
            deleted[table] = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            conn.execute(f'DELETE FROM "{table}"')
        conn.execute("DELETE FROM sqlite_sequence WHERE name IN (?,?,?)", SYNC_CLEAR_ORDER)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return deleted


def verify_local(path: Path) -> None:
    report = schema_report(path)
    missing = [table for table in PRESERVED_LOCAL + LOCAL_CLEAR_ORDER if table not in report["tables"]]
    if missing:
        raise RuntimeError("Schema changed unexpectedly; missing tables: " + ", ".join(missing))
    nonzero = {table: report["counts"][table] for table in LOCAL_CLEAR_ORDER if report["counts"].get(table, 0)}
    if nonzero:
        raise RuntimeError(f"Reset verification failed; non-zero tables: {nonzero}")
    for table in PRESERVED_LOCAL:
        if table not in report["tables"]:
            raise RuntimeError(f"Preserved table missing: {table}")
    admin = sqlite3.connect(path)
    try:
        if not admin.execute("SELECT 1 FROM users WHERE username='admin' LIMIT 1").fetchone():
            raise RuntimeError("Administrator account was not preserved")
    finally:
        admin.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="DEVELOPMENT / SAMPLE DATA RESET")
    parser.add_argument("--database", type=Path, default=LOCAL_DB)
    parser.add_argument("--include-sync-server", action="store_true")
    args = parser.parse_args()

    print("DEVELOPMENT / SAMPLE DATA RESET")
    print(f"Local database: {args.database}")
    print(f"This permanently deletes sample data from: {', '.join(LOCAL_CLEAR_ORDER)}")
    print("Preserved: schema, indexes, foreign keys, admin/users, roles, permissions, settings")
    print(f'Type {CONFIRMATION} to continue, or anything else to cancel: ', end="", flush=True)
    if sys.stdin.readline().strip() != CONFIRMATION:
        print("Cancelled. No database changes were made.")
        return 0

    before = schema_report(args.database)
    print("Foreign-key relationships discovered:")
    for table, fks in before["foreign_keys"].items():
        if fks:
            print(f"  {table}: {fks}")
    backup = backup_database(args.database)
    deleted = clear_local(args.database)
    sync_backup = None
    sync_deleted = {}
    if args.include_sync_server and SYNC_DB.exists():
        print(f'Type {CONFIRMATION} again to reset development sync data at {SYNC_DB}: ', end="", flush=True)
        if sys.stdin.readline().strip() != CONFIRMATION:
            print("Development sync reset skipped; local reset completed.")
        else:
            sync_backup = backup_database(SYNC_DB)
            sync_deleted = clear_sync_server(SYNC_DB)

    verify_local(args.database)
    after = schema_report(args.database)
    print(f"Backup created: {backup}")
    print("Deleted local records:")
    for table, count in deleted.items():
        print(f"  {table}: {count}")
    if args.include_sync_server:
        print(f"Development sync backup: {sync_backup or 'not created'}")
        print("Deleted development sync records:")
        for table, count in sync_deleted.items():
            print(f"  {table}: {count}")
    print("Verification: cleared local targets are zero; admin and preserved schema/settings tables remain.")
    print("Remaining local counts:")
    for table in LOCAL_CLEAR_ORDER + PRESERVED_LOCAL:
        print(f"  {table}: {after['counts'].get(table, 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
