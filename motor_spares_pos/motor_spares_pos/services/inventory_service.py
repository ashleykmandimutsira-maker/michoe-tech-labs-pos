"""
Inventory service for Motor Spares POS.
Handles stock movements, inventory updates, and stock-level tracking.
"""

import logging
from typing import Optional, List
from datetime import datetime

from database.db import get_database_manager
from models.product import Product, StockMovement
from services.product_service import ProductService
from services.sync_service import SyncService
import json

logger = logging.getLogger(__name__)


class InventoryService:
    """Service for managing inventory and stock movements."""

    def __init__(self):
        """Initialize inventory service."""
        self.db = get_database_manager()
        self.product_service = ProductService()
        self.sync = SyncService()

    def record_stock_movement(
        self,
        product_id: int,
        movement_type: str,
        quantity: int,
        reference: Optional[str] = None,
        user_id: Optional[int] = None,
        notes: Optional[str] = None,
    ) -> int:
        """
        Record a stock movement and update product quantity.

        Args:
            product_id: Product ID
            movement_type: Type of movement (PURCHASE, SALE, RETURN, ADJUSTMENT, DAMAGE, TRANSFER, VOID)
            quantity: Amount of stock moved
            reference: Reference number (invoice, PO, etc.)
            user_id: User who made the movement
            notes: Additional notes

        Returns:
            Stock movement record ID

        Raises:
            ValueError: If movement type is invalid or insufficient stock for SALE
        """
        # Validate movement type
        if movement_type not in StockMovement.VALID_TYPES:
            raise ValueError(f"Invalid movement type: {movement_type}")
        if movement_type == "ADJUSTMENT":
            if not isinstance(quantity, int) or quantity == 0:
                raise ValueError(
                    "Adjustment quantity must be a non-zero integer"
                )
        elif quantity < 0:
            raise ValueError("Stock movement quantity cannot be negative")

        # Get current product
        product = self.product_service.get_product_by_id(product_id)
        if not product:
            raise ValueError(f"Product not found: {product_id}")

        previous_quantity = product.quantity_on_hand

        # Calculate new quantity based on movement type
        if movement_type in ["PURCHASE", "RETURN", "ADJUSTMENT"]:
            new_quantity = previous_quantity + quantity
        elif movement_type in ["SALE", "DAMAGE", "TRANSFER", "VOID"]:
            # Check if enough stock for sale
            if movement_type == "SALE" and quantity > previous_quantity:
                raise ValueError(
                    f"Insufficient stock for product {product.part_no}. "
                    f"Available: {previous_quantity}, Requested: {quantity}"
                )
            new_quantity = previous_quantity - quantity
        else:
            new_quantity = previous_quantity

        # Ensure quantity doesn't go negative
        if new_quantity < 0:
            raise ValueError(
                f"Insufficient stock for product {product.part_no}"
            )

        with self.db.transaction() as conn:
            movement_id = conn.execute(
                "INSERT INTO stock_movements (product_id,movement_type,quantity,previous_quantity,new_quantity,reference,user_id,notes) VALUES (?,?,?,?,?,?,?,?)",
                (
                    product_id,
                    movement_type,
                    quantity,
                    previous_quantity,
                    new_quantity,
                    reference,
                    user_id,
                    notes,
                ),
            ).lastrowid
            conn.execute(
                "UPDATE products SET quantity_on_hand = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (new_quantity, product_id),
            )

        movement = self.get_stock_movement(movement_id)
        if movement:
            self.sync.enqueue(
                "STOCK_MOVEMENT",
                movement_id,
                "CREATE",
                json.dumps(movement.to_dict()),
            )
            self.sync.request_background_sync()
        updated_product = self.product_service.get_product_by_id(product_id)
        if updated_product:
            self.sync.enqueue(
                "PRODUCT",
                product_id,
                "UPDATE",
                json.dumps(updated_product.to_dict()),
            )
            self.sync.request_background_sync()

        logger.info(
            f"Stock movement: {product.part_no} ({movement_type}) "
            f"{previous_quantity} -> {new_quantity} (ID: {movement_id})"
        )

        return movement_id

    def _insert_stock_movement(
        self,
        product_id: int,
        movement_type: str,
        quantity: int,
        previous_quantity: int,
        new_quantity: int,
        reference: Optional[str] = None,
        user_id: Optional[int] = None,
        notes: Optional[str] = None,
    ) -> int:
        """Insert a stock movement record into the database."""
        query = """
            INSERT INTO stock_movements (
                product_id, movement_type, quantity,
                previous_quantity, new_quantity, reference,
                user_id, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            product_id,
            movement_type,
            quantity,
            previous_quantity,
            new_quantity,
            reference,
            user_id,
            notes,
        )

        try:
            self.db.execute_update(query, params)
            return self.db.get_last_insert_id()
        except Exception as e:
            logger.error(f"Failed to record stock movement: {e}")
            raise

    def get_stock_movement(self, movement_id: int) -> Optional[StockMovement]:
        """Get a stock movement by ID."""
        query = "SELECT * FROM stock_movements WHERE id = ?"
        results = self.db.execute_query(query, (movement_id,))

        if results:
            return self._row_to_stock_movement(results[0])
        return None

    def get_product_movement_history(
        self,
        product_id: int,
        limit: int = 50,
        offset: int = 0,
    ) -> List[StockMovement]:
        """
        Get stock movement history for a product.

        Args:
            product_id: Product ID
            limit: Number of records to return
            offset: Starting position

        Returns:
            List of StockMovement objects
        """
        query = """
            SELECT * FROM stock_movements
            WHERE product_id = ?
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """
        results = self.db.execute_query(query, (product_id, limit, offset))
        return [self._row_to_stock_movement(row) for row in results]

    def get_recent_movements(self, limit: int = 50) -> List[StockMovement]:
        """
        Get the most recent stock movements across all products.

        Args:
            limit: Number of recent movements to return

        Returns:
            List of StockMovement objects
        """
        query = """
            SELECT * FROM stock_movements
            ORDER BY created_at DESC
            LIMIT ?
        """
        results = self.db.execute_query(query, (limit,))
        return [self._row_to_stock_movement(row) for row in results]

    def get_movements_by_type(
        self,
        movement_type: str,
        limit: int = 50,
    ) -> List[StockMovement]:
        """
        Get stock movements filtered by type.

        Args:
            movement_type: Type of movement to filter by
            limit: Number of records to return

        Returns:
            List of StockMovement objects
        """
        query = """
            SELECT * FROM stock_movements
            WHERE movement_type = ?
            ORDER BY created_at DESC
            LIMIT ?
        """
        results = self.db.execute_query(query, (movement_type, limit))
        return [self._row_to_stock_movement(row) for row in results]

    def adjust_stock(
        self,
        product_id: int,
        quantity_change: int,
        reason: str = "",
        user_id: Optional[int] = None,
    ) -> int:
        """
        Adjust stock for a product (inventory correction, damage, etc.).

        Args:
            product_id: Product ID
            quantity_change: Amount to add/subtract
            reason: Reason for adjustment
            user_id: User making adjustment

        Returns:
            Movement record ID
        """
        return self.record_stock_movement(
            product_id=product_id,
            movement_type="ADJUSTMENT",
            quantity=quantity_change,
            reference=None,
            user_id=user_id,
            notes=reason,
        )

    def receive_stock(
        self,
        product_id: int,
        quantity: int,
        po_number: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> int:
        """
        Receive stock from a supplier (purchase order received).

        Args:
            product_id: Product ID
            quantity: Quantity received
            po_number: Purchase order number
            user_id: Receiving user

        Returns:
            Movement record ID
        """
        return self.record_stock_movement(
            product_id=product_id,
            movement_type="PURCHASE",
            quantity=quantity,
            reference=po_number,
            user_id=user_id,
            notes=f"PO: {po_number}" if po_number else "Stock received",
        )

    def sell_product(
        self,
        product_id: int,
        quantity: int,
        invoice_number: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> int:
        """
        Record a sale (deduct from stock).

        Args:
            product_id: Product ID
            quantity: Quantity sold
            invoice_number: Invoice/receipt number
            user_id: Selling user

        Returns:
            Movement record ID

        Raises:
            ValueError: If insufficient stock
        """
        return self.record_stock_movement(
            product_id=product_id,
            movement_type="SALE",
            quantity=quantity,
            reference=invoice_number,
            user_id=user_id,
            notes=f"Invoice: {invoice_number}" if invoice_number else "Sale",
        )

    def return_product(
        self,
        product_id: int,
        quantity: int,
        reason: str = "",
        user_id: Optional[int] = None,
    ) -> int:
        """
        Process a customer return.

        Args:
            product_id: Product ID
            quantity: Quantity returned
            reason: Return reason
            user_id: Receiving user

        Returns:
            Movement record ID
        """
        return self.record_stock_movement(
            product_id=product_id,
            movement_type="RETURN",
            quantity=quantity,
            reference=None,
            user_id=user_id,
            notes=f"Return: {reason}" if reason else "Customer return",
        )

    def report_damage(
        self,
        product_id: int,
        quantity: int,
        reason: str = "",
        user_id: Optional[int] = None,
    ) -> int:
        """
        Report damaged/destroyed stock.

        Args:
            product_id: Product ID
            quantity: Quantity damaged
            reason: Damage reason
            user_id: Reporting user

        Returns:
            Movement record ID
        """
        return self.record_stock_movement(
            product_id=product_id,
            movement_type="DAMAGE",
            quantity=quantity,
            reference=None,
            user_id=user_id,
            notes=f"Damage: {reason}" if reason else "Damaged stock",
        )

    def transfer_stock(
        self,
        product_id: int,
        quantity: int,
        destination: str = "Another location",
        user_id: Optional[int] = None,
    ) -> int:
        """
        Transfer stock to another location.

        Args:
            product_id: Product ID
            quantity: Quantity transferred
            destination: Destination location
            user_id: Transferring user

        Returns:
            Movement record ID
        """
        return self.record_stock_movement(
            product_id=product_id,
            movement_type="TRANSFER",
            quantity=quantity,
            reference=None,
            user_id=user_id,
            notes=f"Transferred to: {destination}",
        )

    def set_stock_level(
        self,
        product_id: int,
        new_quantity: int,
        reason: str = "",
        user_id: Optional[int] = None,
        reference: Optional[str] = None,
    ) -> Optional[int]:
        """
        Correct a product's stock to an exact count (e.g. from a physical
        stock take or an inventory spreadsheet), in either direction.

        Unlike record_stock_movement('ADJUSTMENT', ...), which only ever
        adds, this computes the signed delta itself so a downward count
        correction is recorded and applied correctly.

        Returns the movement record ID, or None if the quantity is
        unchanged (nothing to record).
        """
        product = self.product_service.get_product_by_id(product_id)
        if not product:
            raise ValueError(f"Product not found: {product_id}")

        previous_quantity = product.quantity_on_hand
        delta = new_quantity - previous_quantity
        if delta == 0:
            return None

        direction = "increase" if delta > 0 else "decrease"
        notes = (
            reason or f"Stock count correction ({direction} of {abs(delta)})"
        )

        if new_quantity < 0:
            raise ValueError("Stock quantity cannot be negative")
        with self.db.transaction() as conn:
            movement_id = conn.execute(
                "INSERT INTO stock_movements (product_id,movement_type,quantity,previous_quantity,new_quantity,reference,user_id,notes) VALUES (?,?,?,?,?,?,?,?)",
                (
                    product_id,
                    "ADJUSTMENT",
                    delta,
                    previous_quantity,
                    new_quantity,
                    reference,
                    user_id,
                    notes,
                ),
            ).lastrowid
            conn.execute(
                "UPDATE products SET quantity_on_hand = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (new_quantity, product_id),
            )

        movement = self.get_stock_movement(movement_id)
        if movement:
            self.sync.enqueue(
                "STOCK_MOVEMENT",
                movement_id,
                "CREATE",
                json.dumps(movement.to_dict()),
            )
            self.sync.request_background_sync()
        updated_product = self.product_service.get_product_by_id(product_id)
        if updated_product:
            self.sync.enqueue(
                "PRODUCT",
                product_id,
                "UPDATE",
                json.dumps(updated_product.to_dict()),
            )
            self.sync.request_background_sync()

        logger.info(
            "Stock level corrected: %s %s -> %s (ID: %s)",
            product.part_no,
            previous_quantity,
            new_quantity,
            movement_id,
        )
        return movement_id

    def get_stock_level(self, product_id: int) -> int:
        """Get current stock level for a product."""
        product = self.product_service.get_product_by_id(product_id)
        return product.quantity_on_hand if product else 0

    def get_movement_summary(self, product_id: int) -> dict:
        """
        Get movement summary for a product.

        Returns dictionary with total movements by type.
        """
        query = """
            SELECT
                movement_type,
                COUNT(*) as count,
                SUM(quantity) as total_quantity
            FROM stock_movements
            WHERE product_id = ?
            GROUP BY movement_type
        """
        results = self.db.execute_query(query, (product_id,))

        summary = {}
        for row in results:
            summary[row["movement_type"]] = {
                "count": row["count"],
                "total_quantity": row["total_quantity"],
            }
        return summary

    @staticmethod
    def _row_to_stock_movement(row) -> StockMovement:
        """Convert database row to StockMovement object."""
        return StockMovement(
            id=row["id"],
            product_id=row["product_id"],
            movement_type=row["movement_type"],
            quantity=row["quantity"],
            previous_quantity=row["previous_quantity"],
            new_quantity=row["new_quantity"],
            reference=row["reference"],
            user_id=row["user_id"],
            notes=row["notes"],
            created_at=(
                datetime.fromisoformat(row["created_at"])
                if row["created_at"]
                else None
            ),
        )
