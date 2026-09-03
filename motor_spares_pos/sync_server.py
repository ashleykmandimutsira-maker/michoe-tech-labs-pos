"""
Development synchronization server for Motor Spares POS.

Run with:
    python sync_server.py

This is a simple local/LAN server for testing the POS sync client. For a real
production deployment, put the API behind authentication, TLS, backups and
proper server infrastructure.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "server_data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "sync_server.db"
HOST = "0.0.0.0"
PORT = 8765


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sync_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_key TEXT NOT NULL UNIQUE,
                shop_id TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS products (
                part_no TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                source_shop TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS customers (
                id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                source_shop TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS product_tombstones (
                part_no TEXT PRIMARY KEY,
                deleted_at TEXT NOT NULL,
                source_shop TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS vehicles (
                id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                source_shop TEXT NOT NULL
            );
            """
        )


class Handler(BaseHTTPRequestHandler):
    server_version = "MotorSparesSync/1.0"

    def _json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        print(f"{self.address_string()} - {format % args}")

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._json(200, {"status": "ok"})
            return
        if parsed.path == "/api/sync/pull":
            query = parse_qs(parsed.query)
            since = (query.get("since") or [""])[0]
            rows = []
            with get_db() as conn:
                if since:
                    result = conn.execute(
                        "SELECT payload, updated_at FROM products WHERE updated_at > ? ORDER BY updated_at ASC",
                        (since,),
                    ).fetchall()
                else:
                    result = conn.execute(
                        "SELECT payload, updated_at FROM products ORDER BY updated_at ASC"
                    ).fetchall()
            for row in result:
                payload = json.loads(row["payload"])
                payload["updated_at"] = row["updated_at"]
                rows.append(payload)
            with get_db() as conn:
                customer_result = conn.execute(
                    "SELECT payload, updated_at FROM customers" + (" WHERE updated_at > ?" if since else "") + " ORDER BY updated_at ASC",
                    (since,) if since else (),
                ).fetchall()
            customer_rows = []
            for row in customer_result:
                payload = json.loads(row["payload"])
                payload["updated_at"] = row["updated_at"]
                customer_rows.append(payload)
            
            
            with get_db() as conn:
                vehicle_result = conn.execute("SELECT payload, updated_at FROM vehicles" + (" WHERE updated_at > ?" if since else "") + " ORDER BY updated_at ASC", (since,) if since else ()).fetchall()
            vehicle_rows = []
            for row in vehicle_result:
                payload = json.loads(row["payload"])
                payload["updated_at"] = row["updated_at"]
                vehicle_rows.append(payload)
            with get_db() as conn:
                deleted_rows = conn.execute(
                    "SELECT part_no, deleted_at FROM product_tombstones" +
                    (" WHERE deleted_at > ?" if since else "") + " ORDER BY deleted_at ASC",
                    (since,) if since else (),
                ).fetchall()
            deleted_products = [dict(row) for row in deleted_rows]
            self._json(
                200,
                {
                    "products": rows,
                    "customers": customer_rows,
                    "vehicles": vehicle_rows,
                    "deleted_products": deleted_products,
                    "cursor": datetime.now(timezone.utc).isoformat(),
                },
            )
            return
        self._json(404, {"error": "Not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/sync/push":
            self._json(404, {"error": "Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length) or b"{}")
            shop_id = str(data.get("shop_id") or "UNKNOWN")
            records = data.get("records") or []
            accepted = []
            now = datetime.now(timezone.utc).isoformat()
            with get_db() as conn:
                for record in records:
                    client_key = str(record.get("client_key") or "")
                    if not client_key:
                        continue
                    entity_type = str(record.get("entity_type") or "")
                    entity_id = str(record.get("entity_id") or "")
                    operation = str(record.get("operation") or "")
                    payload = record.get("payload") or {}
                    payload_text = json.dumps(payload, ensure_ascii=False)
                    conn.execute(
                        """
                        INSERT INTO sync_records(client_key,shop_id,entity_type,entity_id,operation,payload,updated_at)
                        VALUES(?,?,?,?,?,?,?)
                        ON CONFLICT(client_key) DO UPDATE SET
                            payload=excluded.payload,
                            updated_at=excluded.updated_at
                        """,
                        (client_key, shop_id, entity_type, entity_id, operation, payload_text, now),
                    )
                    if entity_type == "PRODUCT" and operation == "DELETE":
                        part_no = str(payload.get("part_no") or "").strip()
                        if part_no:
                            conn.execute("DELETE FROM products WHERE part_no=?", (part_no,))
                            conn.execute("INSERT OR REPLACE INTO product_tombstones(part_no, deleted_at, source_shop) VALUES(?,?,?)", (part_no, now, shop_id))
                    elif entity_type == "PRODUCT":
                        part_no = str(payload.get("part_no") or "").strip()
                        if part_no:
                            conn.execute(
                                """
                                INSERT INTO products(part_no,payload,updated_at,source_shop)
                                VALUES(?,?,?,?)
                                ON CONFLICT(part_no) DO UPDATE SET
                                    payload=excluded.payload,
                                    updated_at=excluded.updated_at,
                                    source_shop=excluded.source_shop
                                """,
                                (part_no, payload_text, now, shop_id),
                            )
                    if entity_type == "CUSTOMER":
                        conn.execute(
                            "INSERT INTO customers(id,payload,updated_at,source_shop) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at, source_shop=excluded.source_shop",
                            (entity_id, payload_text, now, shop_id),
                        )
                    if entity_type == "VEHICLE":
                        conn.execute(
                            "INSERT INTO vehicles(id,payload,updated_at,source_shop) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at, source_shop=excluded.source_shop",
                            (entity_id, payload_text, now, shop_id),
                        )
                    accepted.append({"client_key": client_key, "external_id": f"SERVER-{entity_type}-{entity_id}"})
            self._json(200, {"accepted": accepted})
        except Exception as exc:
            self._json(400, {"error": str(exc)})


if __name__ == "__main__":
    init_db()
    print(f"Motor Spares sync server listening on http://127.0.0.1:{PORT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
