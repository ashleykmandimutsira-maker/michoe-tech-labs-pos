"""
Product service for Motor Spares POS.
Handles all product-related database operations.
"""

import logging
from typing import Optional, List
from datetime import datetime

from database.db import get_database_manager
from models.product import Product, Category, VehicleModel, StockMovement
from services.permission_service import PermissionService
from services.audit_service import AuditService
from services.sync_service import SyncService
from core.events import emit_change
import json

logger = logging.getLogger(__name__)


class ProductService:
    """Service for managing products in the inventory system."""

    def __init__(self):
        """Initialize product service with database manager."""
        self.db = get_database_manager()
        self.sync = SyncService()

    # ==================== PRODUCT OPERATIONS ====================

    def create_product(self, product: Product) -> int:
        """
        Create a new product in the database.

        Args:
            product: Product object to create

        Returns:
            Product ID of the created product

        Raises:
            ValueError: If required fields are missing or barcode/part_no already exists
        """
        if not product.part_no:
            raise ValueError("Part number is required")
        if not product.description:
            raise ValueError("Description is required")

        # User-entered duplicates are validation failures, not database errors.
        # Startup sample initialization performs its own existence check before
        # calling this service, so expected seed records never reach INSERT.
        existing = self.db.execute_query(
            "SELECT id FROM products WHERE part_no = ?", (product.part_no,)
        )
        if existing:
            raise ValueError(
                f"A product with part number '{product.part_no}' already exists"
            )
        if product.barcode:
            existing_barcode = self.db.execute_query(
                "SELECT id FROM products WHERE barcode = ?", (product.barcode,)
            )
            if existing_barcode:
                raise ValueError(
                    f"A product with barcode '{product.barcode}' already exists"
                )

        query = """
            INSERT INTO products (
                barcode, part_no, oem_number, description, brand, category_id,
                vehicle_make, vehicle_model, vehicle_year_from, vehicle_year_to, cost_price, selling_price,
                currency, quantity_on_hand, reorder_level, vat_rate, active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        params = (
            product.barcode,
            product.part_no,
            product.oem_number,
            product.description,
            product.brand,
            product.category_id,
            product.vehicle_make,
            product.vehicle_model,
            product.vehicle_year_from,
            product.vehicle_year_to,
            product.cost_price,
            product.selling_price,
            product.currency,
            product.quantity_on_hand,
            product.reorder_level,
            product.vat_rate,
            product.active,
        )

        try:
            self.db.execute_update(query, params)
            product_id = self.db.get_last_insert_id()
            logger.info(
                f"Created product: {product.part_no} (ID: {product_id})"
            )
            created = self.get_product_by_id(product_id)
            if created:
                self.sync.enqueue(
                    "PRODUCT",
                    product_id,
                    "CREATE",
                    json.dumps(created.to_dict()),
                )
                self.sync.request_background_sync()
            return product_id
        except Exception as e:
            logger.error(f"Failed to create product: {e}")
            raise

    def get_product_by_id(self, product_id: int) -> Optional[Product]:
        """
        Retrieve a product by ID.

        Args:
            product_id: Product ID

        Returns:
            Product object or None if not found
        """
        query = "SELECT * FROM products WHERE id = ?"
        results = self.db.execute_query(query, (product_id,))

        if results:
            return self._row_to_product(results[0])
        return None

    def get_product_by_barcode(self, barcode: str) -> Optional[Product]:
        """
        Retrieve a product by barcode.

        Args:
            barcode: Product barcode

        Returns:
            Product object or None if not found
        """
        query = "SELECT * FROM products WHERE barcode = ? AND active = 1"
        results = self.db.execute_query(query, (barcode,))

        if results:
            return self._row_to_product(results[0])
        return None

    def get_product_by_part_no(self, part_no: str) -> Optional[Product]:
        """
        Retrieve a product by part number.

        Args:
            part_no: Product part number

        Returns:
            Product object or None if not found
        """
        query = "SELECT * FROM products WHERE part_no = ? AND active = 1"
        results = self.db.execute_query(query, (part_no,))

        if results:
            return self._row_to_product(results[0])
        return None

    def get_all_products(self, active_only: bool = True) -> List[Product]:
        """
        Retrieve all products.

        Args:
            active_only: Only return active products

        Returns:
            List of Product objects
        """
        if active_only:
            query = "SELECT * FROM products WHERE active = 1 ORDER BY part_no"
        else:
            query = "SELECT * FROM products ORDER BY part_no"

        results = self.db.execute_query(query)
        return [self._row_to_product(row) for row in results]

    def search_products(self, search_term: str) -> List[Product]:
        """
        Search products by multiple fields.

        Searches: barcode, part_no, description, brand, vehicle_make, vehicle_model

        Args:
            search_term: Search term

        Returns:
            List of matching Product objects
        """
        search_pattern = f"%{search_term}%"
        query = """
            SELECT * FROM products
            WHERE active = 1 AND (
                barcode LIKE ? OR
                part_no LIKE ? OR
                description LIKE ? OR
                brand LIKE ? OR
                vehicle_make LIKE ? OR
                vehicle_model LIKE ? OR
                oem_number LIKE ? OR
                EXISTS (SELECT 1 FROM categories c WHERE c.id = products.category_id AND c.name LIKE ?)
            )
            ORDER BY part_no
        """

        params = (search_pattern,) * 8
        results = self.db.execute_query(query, params)
        return [self._row_to_product(row) for row in results]

    def update_product(self, product: Product) -> bool:
        """
        Update an existing product.

        Args:
            product: Product object with updated values

        Returns:
            True if successful
        """
        if not product.id:
            raise ValueError("Product ID is required for update")

        query = """
            UPDATE products SET
                barcode = ?, part_no = ?, oem_number = ?, description = ?, brand = ?,
                category_id = ?, vehicle_make = ?, vehicle_model = ?, vehicle_year_from = ?, vehicle_year_to = ?,
                cost_price = ?, selling_price = ?, currency = ?,
                quantity_on_hand = ?, reorder_level = ?, vat_rate = ?,
                active = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """

        params = (
            product.barcode,
            product.part_no,
            product.oem_number,
            product.description,
            product.brand,
            product.category_id,
            product.vehicle_make,
            product.vehicle_model,
            product.vehicle_year_from,
            product.vehicle_year_to,
            product.cost_price,
            product.selling_price,
            product.currency,
            product.quantity_on_hand,
            product.reorder_level,
            product.vat_rate,
            product.active,
            product.id,
        )

        try:
            previous = self.get_product_by_id(product.id)
            self.db.execute_update(query, params)
            logger.info(
                f"Updated product: {product.part_no} (ID: {product.id})"
            )
            updated = self.get_product_by_id(product.id)
            if updated:
                if (
                    previous
                    and previous.selling_price != updated.selling_price
                ):
                    AuditService().log_price_change(
                        product.id,
                        None,
                        previous.selling_price,
                        updated.selling_price,
                        "Product update",
                    )
                self.sync.enqueue(
                    "PRODUCT",
                    product.id,
                    "UPDATE",
                    json.dumps(updated.to_dict()),
                )
                self.sync.request_background_sync()
            return True
        except Exception as e:
            logger.error(f"Failed to update product: {e}")
            raise

    def archive_product(
        self,
        product_id: int,
        requesting_user_id: int,
        approving_admin_id: Optional[int] = None,
        reason: str = "",
    ) -> bool:
        """Soft-delete a product after ADMIN permission/authorization.

        Physical DELETE is intentionally never used.  A non-admin caller must
        supply an approving administrator who has both the ADMIN role and the
        explicit DELETE_PRODUCT permission.
        """
        reason = (reason or "").strip()
        requesting_user_id = getattr(
            requesting_user_id, "id", requesting_user_id
        )
        approving_admin_id = getattr(
            approving_admin_id, "id", approving_admin_id
        )
        permissions = PermissionService()
        if permissions.can_archive_product(requesting_user_id):
            approver = requesting_user_id
        else:
            if not approving_admin_id or not permissions.can_archive_product(
                approving_admin_id
            ):
                raise PermissionError(
                    "Product archive requires ADMIN authorization"
                )
            approver = approving_admin_id
        product = self.get_product_by_id(product_id)
        if not product:
            raise ValueError(f"Product not found: {product_id}")
        if not product.active:
            return False
        self.db.execute_update(
            "UPDATE products SET active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (product_id,),
        )
        archived = self.get_product_by_id(product_id)
        if archived:
            self.sync.enqueue(
                "PRODUCT", product_id, "UPDATE", json.dumps(archived.to_dict())
            )
            self.sync.request_background_sync()
        AuditService().log_product_archive(
            product_id, requesting_user_id, approver, reason or None
        )
        logger.info(
            "Archived product %s by user %s (approved by %s)",
            product_id,
            requesting_user_id,
            approver,
        )
        return True

    def archive_all_active_products(
        self,
        requesting_user_id: int,
        reason: str = "",
        request_sync: bool = True,
    ) -> int:
        """Archive the active catalog in one transaction without per-product UI churn."""
        requesting_user_id = getattr(
            requesting_user_id, "id", requesting_user_id
        )
        permissions = PermissionService()
        if not permissions.can_archive_product(requesting_user_id):
            raise PermissionError(
                "Only an authorized administrator can archive all products"
            )
        with self.db.transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM products WHERE active=1 ORDER BY id"
            ).fetchall()
            if not rows:
                return 0
            conn.execute(
                "UPDATE products SET active=0, updated_at=CURRENT_TIMESTAMP WHERE active=1"
            )
            payloads = []
            for row in rows:
                payload = dict(row)
                payload["active"] = False
                payloads.append(
                    (
                        "PRODUCT",
                        row["id"],
                        "UPDATE",
                        json.dumps(payload),
                        "PENDING",
                    )
                )
            conn.executemany(
                """INSERT INTO sync_queue(entity_type,entity_id,operation,payload,status)
                   VALUES(?,?,?,?,?) ON CONFLICT(entity_type,entity_id,operation) DO UPDATE SET
                   payload=excluded.payload,status='PENDING',error_message=NULL,last_attempt=NULL""",
                payloads,
            )
            conn.execute(
                """INSERT INTO audit_logs(action,entity_type,requesting_user_id,approving_user_id,reason,details,status)
                   VALUES('PRODUCTS_BULK_ARCHIVED','PRODUCT',?,?,?,?,'COMPLETED')""",
                (
                    requesting_user_id,
                    requesting_user_id,
                    reason or None,
                    f"Archived {len(rows)} active products",
                ),
            )
        if request_sync:
            self.sync.request_background_sync()
        emit_change(
            "PRODUCT", {"operation": "BULK_ARCHIVE", "count": len(rows)}
        )
        logger.info(
            "Archived %s active products in one bulk operation", len(rows)
        )
        return len(rows)

    def clear_active_catalog(self, requesting_user_id: int) -> dict:
        """Remove active products safely for handover without damaging history.

        Unreferenced products are permanently removed. Products referenced by
        sales, inventory, returns, quotations, or imports are archived so the
        active catalog is empty while its audit trail remains valid.
        """
        requesting_user_id = getattr(
            requesting_user_id, "id", requesting_user_id
        )
        if not PermissionService().can_archive_product(requesting_user_id):
            raise PermissionError(
                "Only an authorized administrator can clear the catalog"
            )
        with self.db.transaction() as conn:
            rows = conn.execute("""
                SELECT p.*,
                  EXISTS(SELECT 1 FROM sale_items si WHERE si.product_id=p.id)
                  OR EXISTS(SELECT 1 FROM stock_movements sm WHERE sm.product_id=p.id)
                  OR EXISTS(SELECT 1 FROM return_items ri WHERE ri.product_id=p.id)
                  OR EXISTS(SELECT 1 FROM quotation_items qi WHERE qi.product_id=p.id)
                  OR EXISTS(SELECT 1 FROM inventory_import_items ii WHERE ii.product_id=p.id) AS has_history
                FROM products p WHERE p.active=1 ORDER BY p.id
            """).fetchall()
            removable = [row for row in rows if not row["has_history"]]
            archived = [row for row in rows if row["has_history"]]
            if archived:
                conn.executemany(
                    "UPDATE products SET active=0,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    [(row["id"],) for row in archived],
                )
            if removable:
                conn.execute(
                    "DROP TRIGGER IF EXISTS prevent_product_physical_delete"
                )
                conn.executemany(
                    "DELETE FROM products WHERE id=?",
                    [(row["id"],) for row in removable],
                )
                conn.executemany(
                    "INSERT OR REPLACE INTO product_tombstones(product_id,part_no) VALUES(?,?)",
                    [(row["id"], row["part_no"]) for row in removable],
                )
                conn.execute(
                    """CREATE TRIGGER prevent_product_physical_delete
                    BEFORE DELETE ON products BEGIN
                    SELECT RAISE(ABORT, 'Products must be archived, not physically deleted'); END"""
                )
            queued = []
            for row in archived:
                payload = dict(row)
                payload["active"] = False
                queued.append(
                    (
                        "PRODUCT",
                        row["id"],
                        "UPDATE",
                        json.dumps(payload),
                        "PENDING",
                    )
                )
            for row in removable:
                queued.append(
                    (
                        "PRODUCT",
                        row["id"],
                        "DELETE",
                        json.dumps(
                            {
                                "id": row["id"],
                                "part_no": row["part_no"],
                                "deleted": True,
                            }
                        ),
                        "PENDING",
                    )
                )
            if queued:
                conn.executemany(
                    """INSERT INTO sync_queue(entity_type,entity_id,operation,payload,status)
                    VALUES(?,?,?,?,?) ON CONFLICT(entity_type,entity_id,operation) DO UPDATE SET
                    payload=excluded.payload,status='PENDING',error_message=NULL,last_attempt=NULL""",
                    queued,
                )
            conn.execute(
                """INSERT INTO audit_logs(action,entity_type,requesting_user_id,approving_user_id,details,status)
                VALUES('PRODUCTS_CATALOG_CLEARED','PRODUCT',?,?,?,'COMPLETED')""",
                (
                    requesting_user_id,
                    requesting_user_id,
                    f"Deleted {len(removable)} unreferenced products; archived {len(archived)} historical products",
                ),
            )
        self.sync.request_background_sync()
        emit_change(
            "PRODUCT",
            {
                "operation": "CATALOG_CLEAR",
                "deleted": len(removable),
                "archived": len(archived),
            },
        )
        return {"deleted": len(removable), "archived": len(archived)}

    def delete_product(
        self,
        product_id: int,
        requesting_user_id: int,
        approving_admin_id: Optional[int] = None,
        reason: str = "",
    ) -> bool:
        """Permanently delete a product only when it has no history."""
        reason = (reason or "").strip()
        requesting_user_id = getattr(
            requesting_user_id, "id", requesting_user_id
        )
        approving_admin_id = getattr(
            approving_admin_id, "id", approving_admin_id
        )
        permissions = PermissionService()
        if permissions.can_archive_product(requesting_user_id):
            approver = requesting_user_id
        elif approving_admin_id and permissions.can_archive_product(
            approving_admin_id
        ):
            approver = approving_admin_id
        else:
            raise PermissionError(
                "Permanent deletion requires ADMIN authorization"
            )
        product = self.get_product_by_id(product_id)
        if not product:
            raise ValueError(f"Product not found: {product_id}")
        history_tables = ("sale_items", "stock_movements", "return_items")
        history = []
        for table in history_tables:
            if self.db.execute_query(
                f"SELECT 1 FROM {table} WHERE product_id=? LIMIT 1",
                (product_id,),
            ):
                history.append(table)
        if history:
            raise ValueError(
                "Product has historical records and cannot be permanently deleted; archive it instead: "
                + ", ".join(history)
            )
        try:
            with self.db.transaction() as conn:
                conn.execute(
                    "DROP TRIGGER IF EXISTS prevent_product_physical_delete"
                )
                conn.execute("DELETE FROM products WHERE id=?", (product_id,))
                conn.execute(
                    "INSERT OR REPLACE INTO product_tombstones(product_id, part_no) VALUES (?, ?)",
                    (product_id, product.part_no),
                )
                conn.execute("""
                    CREATE TRIGGER prevent_product_physical_delete
                    BEFORE DELETE ON products
                    BEGIN
                        SELECT RAISE(ABORT, 'Products must be archived, not physically deleted');
                    END
                """)
            AuditService().log_action(
                "PRODUCT_PERMANENTLY_DELETED",
                "PRODUCT",
                product_id,
                requesting_user_id,
                reason or None,
                f"Approved by: {approver}",
                approving_user_id=approver,
            )
            self.sync.enqueue(
                "PRODUCT",
                product_id,
                "DELETE",
                json.dumps(
                    {
                        "id": product_id,
                        "part_no": product.part_no,
                        "deleted": True,
                    }
                ),
            )
            self.sync.request_background_sync()
            return True
        except Exception:
            logger.exception(
                "Failed to permanently delete product %s", product_id
            )
            raise

    def restore_product(
        self,
        product_id: int,
        requesting_user_id: int,
        approving_admin_id: Optional[int] = None,
        reason: str = "",
    ) -> bool:
        """Restore an archived product after ADMIN authorization."""
        reason = (reason or "").strip()
        requesting_user_id = getattr(
            requesting_user_id, "id", requesting_user_id
        )
        approving_admin_id = getattr(
            approving_admin_id, "id", approving_admin_id
        )
        permissions = PermissionService()
        if permissions.can_restore_product(requesting_user_id):
            approver = requesting_user_id
        else:
            if not approving_admin_id or not permissions.can_restore_product(
                approving_admin_id
            ):
                raise PermissionError(
                    "Product restore requires ADMIN authorization"
                )
            approver = approving_admin_id
        product = self.get_product_by_id(product_id)
        if not product:
            raise ValueError(f"Product not found: {product_id}")
        if product.active:
            return False
        self.db.execute_update(
            "UPDATE products SET active = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (product_id,),
        )
        restored = self.get_product_by_id(product_id)
        if restored:
            self.sync.enqueue(
                "PRODUCT", product_id, "UPDATE", json.dumps(restored.to_dict())
            )
            self.sync.request_background_sync()
        AuditService().log_product_restore(
            product_id, requesting_user_id, approver, reason or None
        )
        logger.info(
            "Restored product %s by user %s (approved by %s)",
            product_id,
            requesting_user_id,
            approver,
        )
        return True

    def get_low_stock_products(self) -> List[Product]:
        """
        Get all products with stock at or below reorder level.

        Returns:
            List of low-stock Product objects
        """
        query = """
            SELECT * FROM products
            WHERE active = 1 AND quantity_on_hand <= reorder_level
            ORDER BY quantity_on_hand ASC
        """
        results = self.db.execute_query(query)
        return [self._row_to_product(row) for row in results]

    def get_out_of_stock_products(self) -> List[Product]:
        """
        Get all products that are out of stock.

        Returns:
            List of out-of-stock Product objects
        """
        query = """
            SELECT * FROM products
            WHERE active = 1 AND quantity_on_hand = 0
            ORDER BY part_no
        """
        results = self.db.execute_query(query)
        return [self._row_to_product(row) for row in results]

    def get_products_by_vehicle(
        self, vehicle_make: str, vehicle_model: str = ""
    ) -> List[Product]:
        """
        Get all products for a specific vehicle.

        Args:
            vehicle_make: Vehicle make (e.g., 'Toyota')
            vehicle_model: Vehicle model (e.g., 'Corolla')

        Returns:
            List of Product objects for the vehicle
        """
        if vehicle_model:
            query = """
                SELECT * FROM products
                WHERE active = 1 AND vehicle_make = ? AND vehicle_model = ?
                ORDER BY category_id, description
            """
            results = self.db.execute_query(
                query, (vehicle_make, vehicle_model)
            )
        else:
            query = """
                SELECT * FROM products
                WHERE active = 1 AND vehicle_make = ?
                ORDER BY vehicle_model, category_id, description
            """
            results = self.db.execute_query(query, (vehicle_make,))

        return [self._row_to_product(row) for row in results]

    def get_inventory_value(self) -> float:
        """
        Calculate total value of inventory at cost price.

        Returns:
            Total inventory value in default currency
        """
        query = "SELECT SUM(cost_price * quantity_on_hand) as total FROM products WHERE active = 1"
        results = self.db.execute_query(query)

        if results and results[0]["total"]:
            return results[0]["total"]
        return 0.0

    def get_inventory_summary(self) -> dict:
        """
        Get a summary of inventory statistics.

        Returns:
            Dictionary with inventory metrics
        """
        query = """
            SELECT
                COUNT(*) as total_products,
                SUM(CASE WHEN quantity_on_hand > 0 THEN 1 ELSE 0 END) as in_stock,
                SUM(CASE WHEN quantity_on_hand = 0 THEN 1 ELSE 0 END) as out_of_stock,
                SUM(CASE WHEN quantity_on_hand <= reorder_level THEN 1 ELSE 0 END) as low_stock,
                SUM(quantity_on_hand) as total_units,
                SUM(cost_price * quantity_on_hand) as inventory_value
            FROM products
            WHERE active = 1
        """
        results = self.db.execute_query(query)

        if results:
            row = results[0]
            return {
                "total_products": row["total_products"] or 0,
                "in_stock": row["in_stock"] or 0,
                "out_of_stock": row["out_of_stock"] or 0,
                "low_stock": row["low_stock"] or 0,
                "total_units": row["total_units"] or 0,
                "inventory_value": row["inventory_value"] or 0.0,
            }
        return {
            "total_products": 0,
            "in_stock": 0,
            "out_of_stock": 0,
            "low_stock": 0,
            "total_units": 0,
            "inventory_value": 0.0,
        }

    # ==================== CATEGORY OPERATIONS ====================

    def create_category(self, category: Category) -> int:
        """
        Create a new product category.

        Args:
            category: Category object

        Returns:
            Category ID
        """
        if not category.name:
            raise ValueError("Category name is required")

        query = "INSERT INTO categories (name, description) VALUES (?, ?)"
        params = (category.name, category.description)

        try:
            self.db.execute_update(query, params)
            category_id = self.db.get_last_insert_id()
            logger.info(
                f"Created category: {category.name} (ID: {category_id})"
            )
            return category_id
        except Exception as e:
            logger.error(f"Failed to create category: {e}")
            raise

    def get_all_categories(self) -> List[Category]:
        """Get all product categories."""
        query = "SELECT * FROM categories ORDER BY name"
        results = self.db.execute_query(query)
        return [self._row_to_category(row) for row in results]

    def get_category_by_id(self, category_id: int) -> Optional[Category]:
        """Get category by ID."""
        query = "SELECT * FROM categories WHERE id = ?"
        results = self.db.execute_query(query, (category_id,))

        if results:
            return self._row_to_category(results[0])
        return None

    # ==================== VEHICLE MODEL OPERATIONS ====================

    def create_vehicle_model(self, vehicle: VehicleModel) -> int:
        """Create a new vehicle model."""
        if not vehicle.make or not vehicle.model:
            raise ValueError("Vehicle make and model are required")

        query = """
            INSERT INTO vehicle_models (make, model, year_from, year_to)
            VALUES (?, ?, ?, ?)
        """
        params = (
            vehicle.make,
            vehicle.model,
            vehicle.year_from,
            vehicle.year_to,
        )

        try:
            self.db.execute_update(query, params)
            vehicle_id = self.db.get_last_insert_id()
            logger.info(
                f"Created vehicle: {vehicle.make} {vehicle.model} (ID: {vehicle_id})"
            )
            return vehicle_id
        except Exception as e:
            logger.error(f"Failed to create vehicle model: {e}")
            raise

    def get_all_vehicle_models(self) -> List[VehicleModel]:
        """Get all vehicle models."""
        query = "SELECT * FROM vehicle_models ORDER BY make, model"
        results = self.db.execute_query(query)
        return [self._row_to_vehicle(row) for row in results]

    def get_vehicle_models_by_make(self, make: str) -> List[VehicleModel]:
        """Get all models for a vehicle make."""
        query = "SELECT * FROM vehicle_models WHERE make = ? ORDER BY model"
        results = self.db.execute_query(query, (make,))
        return [self._row_to_vehicle(row) for row in results]

    # ==================== HELPER METHODS ====================

    @staticmethod
    def _row_to_product(row) -> Product:
        """Convert database row to Product object."""
        return Product(
            id=row["id"],
            barcode=row["barcode"],
            part_no=row["part_no"],
            oem_number=(
                row["oem_number"] if "oem_number" in row.keys() else None
            ),
            description=row["description"],
            brand=row["brand"],
            category_id=row["category_id"],
            vehicle_make=row["vehicle_make"],
            vehicle_model=row["vehicle_model"],
            vehicle_year_from=(
                row["vehicle_year_from"]
                if "vehicle_year_from" in row.keys()
                else None
            ),
            vehicle_year_to=(
                row["vehicle_year_to"]
                if "vehicle_year_to" in row.keys()
                else None
            ),
            cost_price=row["cost_price"],
            selling_price=row["selling_price"],
            currency=row["currency"],
            quantity_on_hand=row["quantity_on_hand"],
            reorder_level=row["reorder_level"],
            vat_rate=row["vat_rate"],
            active=bool(row["active"]),
            created_at=(
                datetime.fromisoformat(row["created_at"])
                if row["created_at"]
                else None
            ),
            updated_at=(
                datetime.fromisoformat(row["updated_at"])
                if row["updated_at"]
                else None
            ),
        )

    @staticmethod
    def _row_to_category(row) -> Category:
        """Convert database row to Category object."""
        return Category(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            created_at=(
                datetime.fromisoformat(row["created_at"])
                if row["created_at"]
                else None
            ),
            updated_at=(
                datetime.fromisoformat(row["updated_at"])
                if row["updated_at"]
                else None
            ),
        )

    @staticmethod
    def _row_to_vehicle(row) -> VehicleModel:
        """Convert database row to VehicleModel object."""
        return VehicleModel(
            id=row["id"],
            make=row["make"],
            model=row["model"],
            year_from=row["year_from"],
            year_to=row["year_to"],
            created_at=(
                datetime.fromisoformat(row["created_at"])
                if row["created_at"]
                else None
            ),
        )
