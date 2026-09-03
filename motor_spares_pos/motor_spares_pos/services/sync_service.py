"""
Offline-first synchronization service for the Motor Spares POS.

The client keeps every change in SQLite first. When a real synchronization
endpoint is configured and reachable, pending records are uploaded and newer
server product/price updates are downloaded.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from database.db import get_database_manager
from core.events import emit_change

logger = logging.getLogger(__name__)
_SYNC_LOCK = threading.Lock()


class SyncService:
    """Manage local sync queue and HTTP-based synchronization."""

    def __init__(self):
        self.db = get_database_manager()
        self.config = self._load_config()

    @staticmethod
    def _load_config() -> dict:
        path = Path(__file__).resolve().parent.parent / "config.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    @property
    def shop_id(self) -> str:
        return str(self.config.get("shop_id") or "DEFAULT-SHOP")

    @property
    def endpoint(self) -> str:
        """Read the current endpoint from settings first, then config.json."""
        row = self.db.execute_query(
            "SELECT value FROM settings WHERE key = 'sync_endpoint' LIMIT 1"
        )
        configured = row[0]["value"] if row else ""
        return (
            (configured or self.config.get("server_url") or "")
            .strip()
            .rstrip("/")
        )

    @property
    def timeout(self) -> float:
        try:
            return max(
                2.0, min(float(self.config.get("sync_timeout", 5)), 15.0)
            )
        except (TypeError, ValueError):
            return 5.0

    def enqueue(
        self,
        entity_type: str,
        entity_id: int,
        operation: str,
        payload: Optional[str] = None,
    ) -> int:
        query = """
            INSERT INTO sync_queue (entity_type, entity_id, operation, payload, status)
            VALUES (?, ?, ?, ?, 'PENDING')
            ON CONFLICT(entity_type, entity_id, operation) DO UPDATE SET
                payload = COALESCE(excluded.payload, sync_queue.payload),
                status = 'PENDING',
                error_message = NULL,
                last_attempt = NULL
        """
        # Upsert may INSERT or UPDATE. SQLite's lastrowid is not reliable after
        # an UPDATE, so always resolve the queue row by its unique business key.
        self.db.execute_update(
            query, (entity_type, entity_id, operation, payload)
        )
        rows = self.db.execute_query(
            "SELECT id FROM sync_queue WHERE entity_type = ? AND entity_id = ? AND operation = ? LIMIT 1",
            (entity_type, entity_id, operation),
        )
        if not rows:
            raise RuntimeError("Failed to create sync queue record")
        queue_id = int(rows[0]["id"])
        logger.info(
            "Queued for sync: %s#%s (%s) -> queue %s",
            entity_type,
            entity_id,
            operation,
            queue_id,
        )
        # Every local mutation in the app flows through here, so this is the
        # one place we need to broadcast "the data changed" for any open
        # screen (dashboard, inventory, etc.) to pick up immediately.
        emit_change(
            entity_type, {"entity_id": entity_id, "operation": operation}
        )
        return queue_id

    def get_pending(self) -> List[dict]:
        rows = self.db.execute_query(
            "SELECT * FROM sync_queue WHERE status = 'PENDING' ORDER BY created_at ASC"
        )
        return rows or []

    def get_failed(self) -> List[dict]:
        rows = self.db.execute_query(
            "SELECT * FROM sync_queue WHERE status = 'FAILED' ORDER BY created_at ASC"
        )
        return rows or []

    def get_sync_status(self) -> dict:
        rows = self.db.execute_query(
            "SELECT status, COUNT(*) count FROM sync_queue GROUP BY status"
        )
        status = {"PENDING": 0, "SYNCING": 0, "SYNCED": 0, "FAILED": 0}
        for row in rows:
            status[row["status"]] = row["count"]
        return status

    def server_configured(self) -> bool:
        return bool(self.endpoint)

    def is_online(self) -> bool:
        """Return true only when the configured sync endpoint responds."""
        endpoint = self.endpoint
        if not endpoint:
            return False
        url = f"{endpoint}/api/health"
        try:
            with urlopen(
                Request(url, headers={"Accept": "application/json"}),
                timeout=self.timeout,
            ) as response:
                return 200 <= response.status < 300
        except (URLError, HTTPError, TimeoutError, OSError):
            return False

    def connection_status(self) -> str:
        if not self.server_configured():
            return "NOT CONFIGURED"
        return "ONLINE" if self.is_online() else "OFFLINE"

    def request_background_sync(self) -> None:
        """Start a non-blocking sync attempt after a local mutation.

        This is deliberately best-effort: offline clients keep their queue and
        the normal timer/manual Sync Now will retry later.
        """
        if os.environ.get("POS_DISABLE_BACKGROUND_SYNC") == "1":
            return
        if not self.server_configured() or not _SYNC_LOCK.acquire(
            blocking=False
        ):
            return

        def worker():
            try:
                self.sync_now(_lock_held=True)
            except Exception:
                logger.exception("Background synchronization failed")
            finally:
                _SYNC_LOCK.release()

        threading.Thread(
            target=worker, name="POS-BackgroundSync", daemon=True
        ).start()

    def sync_now(self, max_retries: int = 3, _lock_held: bool = False) -> dict:
        """Upload local changes then pull product/price updates from the server."""
        acquired_here = False
        if not _lock_held:
            acquired_here = _SYNC_LOCK.acquire(blocking=False)
            if not acquired_here:
                return {
                    "status": "BUSY",
                    "uploaded": 0,
                    "failed": 0,
                    "downloaded": 0,
                    "pending": self.get_sync_status().get("PENDING", 0),
                    "message": "Synchronization is already in progress.",
                }

        try:
            return self._sync_now_impl(max_retries=max_retries)
        finally:
            if acquired_here:
                _SYNC_LOCK.release()

    def _sync_now_impl(self, max_retries: int = 3) -> dict:
        if not self.server_configured():
            return {
                "status": "NOT_CONFIGURED",
                "uploaded": 0,
                "failed": 0,
                "downloaded": 0,
                "pending": self.get_sync_status().get("PENDING", 0),
                "message": "No synchronization endpoint is configured.",
            }

        if not self.is_online():
            return {
                "status": "OFFLINE",
                "uploaded": 0,
                "failed": 0,
                "downloaded": 0,
                "pending": self.get_sync_status().get("PENDING", 0),
                "message": "Synchronization server is unreachable.",
            }

        uploaded = 0
        failed = 0
        for row in self.get_pending():
            queue_id = row["id"]
            self._mark_syncing(queue_id)
            try:
                record = self._queue_record(row)
                response = self._request_json(
                    "POST",
                    f"{self.endpoint}/api/sync/push",
                    {"shop_id": self.shop_id, "records": [record]},
                )
                accepted = response.get("accepted") or []
                if not accepted:
                    raise RuntimeError(
                        "Server did not acknowledge the sync record"
                    )
                external_id = str(
                    accepted[0].get("external_id") or record["client_key"]
                )
                self.mark_synced(queue_id, external_id)
                self.log_sync(queue_id, True, json.dumps(response))
                uploaded += 1
            except Exception as exc:
                failed += 1
                self.mark_failed(queue_id, str(exc))
                self.log_sync(queue_id, False, str(exc))
                logger.warning("Sync failed for queue %s: %s", queue_id, exc)

        downloaded = 0
        try:
            downloaded = self._pull_updates()
        except Exception as exc:
            logger.warning("Pull synchronization failed: %s", exc)

        status = self.get_sync_status()
        if uploaded or downloaded:
            # Records pulled from the server (e.g. another terminal's stock
            # changes) also need to refresh whatever screen is open here.
            emit_change(
                "SYNC", {"uploaded": uploaded, "downloaded": downloaded}
            )
        # A failed upload may still leave pending work. The queue is authoritative.
        return {
            "status": "SYNCED" if failed == 0 else "PARTIAL",
            "uploaded": uploaded,
            "failed": failed,
            "downloaded": downloaded,
            "pending": status.get("PENDING", 0) + status.get("FAILED", 0),
            "message": (
                "Synchronization completed."
                if failed == 0
                else "Synchronization completed with failures."
            ),
        }

    def _request_json(
        self, method: str, url: str, data: Optional[dict] = None
    ) -> dict:
        body = None
        headers = {"Accept": "application/json"}
        if data is not None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(url, data=body, method=method, headers=headers)
        with urlopen(request, timeout=self.timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}

    def _mark_syncing(self, queue_id: int) -> None:
        self.db.execute_update(
            "UPDATE sync_queue SET status='SYNCING', attempts=attempts+1, retry_count=retry_count+1, last_attempt=CURRENT_TIMESTAMP WHERE id=?",
            (queue_id,),
        )

    def _queue_record(self, row: dict) -> dict:
        payload = row["payload"]
        if not payload:
            payload = json.dumps(
                self._build_payload(
                    row["entity_type"], row["entity_id"], row["operation"]
                )
            )
        return {
            "client_key": f"{self.shop_id}:{row['entity_type']}:{row['entity_id']}:{row['operation']}",
            "entity_type": row["entity_type"],
            "entity_id": row["entity_id"],
            "operation": row["operation"],
            "payload": (
                json.loads(payload) if isinstance(payload, str) else payload
            ),
            "created_at": row["created_at"],
        }

    def _build_payload(
        self, entity_type: str, entity_id: int, operation: str
    ) -> dict:
        if entity_type == "PRODUCT":
            row = self.db.execute_query(
                "SELECT * FROM products WHERE id=?", (entity_id,)
            )
            return (
                dict(row[0])
                if row
                else {"id": entity_id, "operation": operation}
            )
        if entity_type == "STOCK_MOVEMENT":
            row = self.db.execute_query(
                "SELECT * FROM stock_movements WHERE id=?", (entity_id,)
            )
            return (
                dict(row[0])
                if row
                else {"id": entity_id, "operation": operation}
            )
        if entity_type == "SALE":
            sale = self.db.execute_query(
                "SELECT * FROM sales WHERE id=?", (entity_id,)
            )
            if not sale:
                return {"id": entity_id, "operation": operation}
            result = dict(sale[0])
            result["items"] = [
                dict(r)
                for r in self.db.execute_query(
                    "SELECT * FROM sale_items WHERE sale_id=? ORDER BY id",
                    (entity_id,),
                )
            ]
            result["payments"] = [
                dict(r)
                for r in self.db.execute_query(
                    "SELECT * FROM payments WHERE sale_id=? ORDER BY id",
                    (entity_id,),
                )
            ]
            return result
        if entity_type == "RETURN":
            ret = self.db.execute_query(
                "SELECT * FROM returns WHERE id=?", (entity_id,)
            )
            result = (
                dict(ret[0])
                if ret
                else {"id": entity_id, "operation": operation}
            )
            result["items"] = [
                dict(r)
                for r in self.db.execute_query(
                    "SELECT * FROM return_items WHERE return_id=? ORDER BY id",
                    (entity_id,),
                )
            ]
            return result
        if entity_type == "REFUND":
            row = self.db.execute_query(
                "SELECT * FROM refunds WHERE id=?", (entity_id,)
            )
            return (
                dict(row[0])
                if row
                else {"id": entity_id, "operation": operation}
            )
        if entity_type == "CUSTOMER":
            row = self.db.execute_query(
                "SELECT * FROM customers WHERE id=?", (entity_id,)
            )
            return (
                dict(row[0])
                if row
                else {"id": entity_id, "operation": operation}
            )
        if entity_type == "VEHICLE":
            row = self.db.execute_query(
                "SELECT * FROM vehicles WHERE id=?", (entity_id,)
            )
            return (
                dict(row[0])
                if row
                else {"id": entity_id, "operation": operation}
            )
        return {"id": entity_id, "operation": operation}

    def _pull_updates(self) -> int:
        row = self.db.execute_query(
            "SELECT value FROM settings WHERE key='sync_last_pulled_at' LIMIT 1"
        )
        since = row[0]["value"] if row else ""
        query = urlencode({"shop_id": self.shop_id, "since": since})
        response = self._request_json(
            "GET", f"{self.endpoint}/api/sync/pull?{query}"
        )
        products = response.get("products") or []
        customers = response.get("customers") or []
        vehicles = response.get("vehicles") or []
        deleted_products = response.get("deleted_products") or []
        applied = 0
        for product in products:
            if self._apply_remote_product(product):
                applied += 1
        for customer in customers:
            if self._apply_remote_customer(customer):
                applied += 1
        for vehicle in vehicles:
            if self._apply_remote_vehicle(vehicle):
                applied += 1
        for product in deleted_products:
            if self._apply_remote_product_delete(product):
                applied += 1

        cursor = response.get("cursor")
        if cursor:
            self.db.execute_update(
                "INSERT INTO settings(key,value,data_type) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP",
                ("sync_last_pulled_at", str(cursor), "string"),
            )
        return applied

    def _apply_remote_product_delete(self, remote: dict) -> bool:
        part_no = str(remote.get("part_no") or "").strip()
        if not part_no:
            return False
        rows = self.db.execute_query(
            "SELECT id FROM products WHERE part_no=?", (part_no,)
        )
        if rows:
            self.db.execute_update(
                "UPDATE products SET active=0, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (rows[0]["id"],),
            )
        return True

    def _apply_remote_customer(self, remote: dict) -> bool:
        customer_id = remote.get("id")
        if customer_id is None or not str(remote.get("name") or "").strip():
            return False
        if self._has_pending_local_change("CUSTOMER", customer_id):
            return False
        fields = [
            "customer_code",
            "name",
            "company",
            "phone",
            "email",
            "address",
            "city",
            "country",
            "id_number",
            "vehicle_make",
            "vehicle_model",
            "vehicle_registration",
        ]
        values = [remote.get(field) for field in fields]
        existing = self.db.execute_query(
            "SELECT id FROM customers WHERE id=?", (customer_id,)
        )
        if existing:
            self.db.execute_update(
                "UPDATE customers SET "
                + ", ".join(f"{field}=?" for field in fields)
                + ", active=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                tuple(values)
                + (1 if remote.get("active", True) else 0, customer_id),
            )
        else:
            self.db.execute_update(
                "INSERT INTO customers (id,"
                + ",".join(fields)
                + ",active) VALUES (?"
                + ",?" * len(fields)
                + ",?)",
                (customer_id,)
                + tuple(values)
                + (1 if remote.get("active", True) else 0,),
            )
        return True

    def _apply_remote_vehicle(self, remote: dict) -> bool:
        vehicle_id = remote.get("id")
        registration = str(remote.get("registration_number") or "").strip()
        customer_id = remote.get("customer_id")
        if (
            vehicle_id is None
            or not registration
            or customer_id is None
            or self._has_pending_local_change("VEHICLE", vehicle_id)
        ):
            return False
        if not self.db.execute_query(
            "SELECT id FROM customers WHERE id=?", (customer_id,)
        ):
            return False
        fields = [
            "customer_id",
            "registration_number",
            "make",
            "model",
            "year",
            "engine",
            "vin",
            "color",
            "notes",
        ]
        values = [remote.get(field) for field in fields]
        existing = self.db.execute_query(
            "SELECT id FROM vehicles WHERE id=?", (vehicle_id,)
        )
        if existing:
            self.db.execute_update(
                "UPDATE vehicles SET "
                + ", ".join(f"{field}=?" for field in fields)
                + ",active=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                tuple(values)
                + (1 if remote.get("active", True) else 0, vehicle_id),
            )
        else:
            self.db.execute_update(
                "INSERT INTO vehicles(id,"
                + ",".join(fields)
                + ",active) VALUES (?"
                + ",?" * len(fields)
                + ",?)",
                (vehicle_id,)
                + tuple(values)
                + (1 if remote.get("active", True) else 0,),
            )
        return True

    def _has_pending_local_change(
        self, entity_type: str, entity_id: Optional[int]
    ) -> bool:
        if entity_id is None:
            return False
        return bool(
            self.db.execute_query(
                "SELECT 1 FROM sync_queue WHERE entity_type=? AND entity_id=? AND operation IN ('CREATE','UPDATE') AND status IN ('PENDING','SYNCING','FAILED') LIMIT 1",
                (entity_type, entity_id),
            )
        )

    def _has_pending_local_product_change(
        self, product_id: Optional[int]
    ) -> bool:
        if product_id is None:
            return False
        rows = self.db.execute_query(
            "SELECT 1 FROM sync_queue WHERE entity_type='PRODUCT' AND entity_id=? AND operation IN ('CREATE','UPDATE') AND status IN ('PENDING','SYNCING','FAILED') LIMIT 1",
            (product_id,),
        )
        return bool(rows)

    def _apply_remote_product(self, remote: dict) -> bool:
        part_no = str(remote.get("part_no") or "").strip()
        if not part_no:
            return False
        if self.db.execute_query(
            "SELECT 1 FROM product_tombstones WHERE part_no=? LIMIT 1",
            (part_no,),
        ):
            return False

        existing = self.db.execute_query(
            "SELECT * FROM products WHERE part_no=? LIMIT 1", (part_no,)
        )
        if existing:
            product_id = existing[0]["id"]
            if self._has_pending_local_product_change(product_id):
                logger.info(
                    "Skipping remote product update for %s because local changes are pending",
                    part_no,
                )
                return False
            local_updated = existing[0]["updated_at"] or ""
            remote_updated = str(remote.get("updated_at") or "")
            if (
                remote_updated
                and local_updated
                and remote_updated <= local_updated
            ):
                return False
            fields = [
                "barcode",
                "description",
                "brand",
                "category_id",
                "vehicle_make",
                "vehicle_model",
                "cost_price",
                "selling_price",
                "currency",
                "quantity_on_hand",
                "reorder_level",
                "vat_rate",
                "active",
            ]
            values = [remote.get(field) for field in fields]
            self.db.execute_update(
                "UPDATE products SET "
                + ", ".join(f"{field}=?" for field in fields)
                + ", updated_at=CURRENT_TIMESTAMP WHERE id=?",
                tuple(values) + (product_id,),
            )
            return True

        try:
            self.db.execute_update(
                """INSERT INTO products (
                    barcode, part_no, description, brand, category_id, vehicle_make, vehicle_model,
                    cost_price, selling_price, currency, quantity_on_hand, reorder_level, vat_rate, active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    remote.get("barcode"),
                    part_no,
                    remote.get("description") or part_no,
                    remote.get("brand") or "",
                    remote.get("category_id"),
                    remote.get("vehicle_make"),
                    remote.get("vehicle_model"),
                    float(remote.get("cost_price") or 0),
                    float(remote.get("selling_price") or 0),
                    remote.get("currency") or "USD",
                    int(remote.get("quantity_on_hand") or 0),
                    int(remote.get("reorder_level") or 5),
                    float(remote.get("vat_rate") or 15),
                    1 if remote.get("active", True) else 0,
                ),
            )
            return True
        except Exception as exc:
            logger.warning(
                "Could not apply remote product %s: %s", part_no, exc
            )
            return False

    def mark_synced(self, queue_id: int, external_id: str) -> bool:
        try:
            self.db.execute_update(
                "UPDATE sync_queue SET status='SYNCED', external_id=?, synced_at=CURRENT_TIMESTAMP WHERE id=?",
                (external_id, queue_id),
            )
            return True
        except Exception as exc:
            logger.error(
                "Failed to mark sync row %s as synced: %s", queue_id, exc
            )
            return False

    def mark_failed(self, queue_id: int, error_message: str = "") -> bool:
        try:
            self.db.execute_update(
                "UPDATE sync_queue SET status='FAILED', error_message=? WHERE id=?",
                (error_message, queue_id),
            )
            return True
        except Exception as exc:
            logger.error(
                "Failed to mark sync row %s as failed: %s", queue_id, exc
            )
            return False

    def retry_failed(self, max_retries: int = 3) -> int:
        self.db.execute_update(
            "UPDATE sync_queue SET status='PENDING', error_message=NULL WHERE status='FAILED' AND retry_count < ?",
            (max_retries,),
        )
        rows = self.db.execute_query(
            "SELECT COUNT(*) count FROM sync_queue WHERE status='PENDING'", ()
        )
        return int(rows[0]["count"]) if rows else 0

    def log_sync(
        self,
        queue_id: int,
        success: bool,
        server_response: Optional[str] = None,
    ) -> bool:
        row = self.db.execute_query(
            "SELECT entity_type,entity_id,operation FROM sync_queue WHERE id=?",
            (queue_id,),
        )
        if not row:
            return False
        try:
            self.db.execute_update(
                "INSERT INTO sync_log(entity_type,entity_id,operation,status,external_id,queue_id,success,server_response) VALUES(?,?,?,?,?,?,?,?)",
                (
                    row[0]["entity_type"],
                    row[0]["entity_id"],
                    row[0]["operation"],
                    "SUCCESS" if success else "FAILED",
                    None,
                    queue_id,
                    1 if success else 0,
                    server_response,
                ),
            )
            return True
        except Exception as exc:
            logger.error("Failed to write sync log: %s", exc)
            return False

    def clear_synced(self, days_old: int = 30) -> int:
        try:
            return self.db.execute_update(
                "DELETE FROM sync_queue WHERE status='SYNCED' AND synced_at < datetime('now', '-' || ? || ' days')",
                (days_old,),
            )
        except Exception as exc:
            logger.error("Failed to clear synced entries: %s", exc)
            return 0
