"""
Returns and refunds service.
PHASE 2: Returns management with complex business logic.
"""

import logging
from typing import Optional, List
from datetime import datetime
import uuid

from database.db import get_database_manager
from models.return_refund import Return, ReturnItem, Refund
from models.sale import Sale
from services.sales_service import SalesService
from services.inventory_service import InventoryService
from services.permission_service import PermissionService
from services.sync_service import SyncService
import json

logger = logging.getLogger(__name__)


class ReturnsService:
    """Service for managing product returns, refunds, and exchanges."""

    # Return limits and approval requirements
    RETURN_LIMITS = {
        "DAILY_LIMIT_USD": 5000,
        "DAILY_LIMIT_ZIG": 500000,
        "LARGE_REFUND_THRESHOLD_USD": 500,
        "LARGE_REFUND_THRESHOLD_ZIG": 50000,
    }

    # Stock conditions and their handling
    STOCK_CONDITIONS = {
        "GOOD": "Add to sellable inventory",
        "DAMAGED": "Do not add to sellable inventory",
        "DEFECTIVE": "Do not add to sellable inventory",
        "WRONG_PART": "Can return to stock if resellable",
        "USED": "Do not add to sellable inventory",
    }

    def __init__(self):
        """Initialize returns service."""
        self.db = get_database_manager()
        self.sales_service = SalesService()
        self.inventory_service = InventoryService()
        self.permission_service = PermissionService()
        self.sync = SyncService()

    def find_original_sale(self, invoice_number: str) -> Optional[Sale]:
        """
        Find the original sale by invoice number.

        Args:
            invoice_number: Invoice number to look up

        Returns:
            Sale object with items and quantities
        """
        sale = self.sales_service.get_sale_by_invoice_number(invoice_number)
        if not sale:
            return None

        return sale

    def search_original_invoices(self, term: str) -> list[dict]:
        """Find completed invoices by number, customer, phone, or registration."""
        pattern = f"%{term.strip()}%"
        return [
            dict(row)
            for row in self.db.execute_query(
                """SELECT i.invoice_number,i.created_at,i.customer_name,i.customer_phone,
                      i.vehicle_registration,i.total,i.status
               FROM invoices i WHERE i.status NOT IN ('VOIDED','DRAFT') AND
               (i.invoice_number LIKE ? OR i.customer_name LIKE ? OR i.customer_phone LIKE ? OR i.vehicle_registration LIKE ?)
               ORDER BY i.created_at DESC LIMIT 50""",
                (pattern, pattern, pattern, pattern),
            )
        ]

    def calculate_returnable_quantity(
        self, product_id: int, original_qty: int, sale_id: int
    ) -> int:
        """
        Calculate how much of a product can be returned.

        Prevents over-returning by checking:
        - Original quantity in sale
        - Already returned quantity

        Args:
            product_id: Product ID
            original_qty: Original quantity sold
            sale_id: Sale ID

        Returns:
            Maximum returnable quantity
        """
        # Get quantity already returned for this product from this sale
        query = """
            SELECT COALESCE(SUM(ri.quantity), 0) as returned_qty
            FROM return_items ri
            INNER JOIN returns r ON ri.return_id = r.id
            WHERE r.original_sale_id = ? AND ri.product_id = ? AND r.status != 'REJECTED'
        """

        results = self.db.execute_query(query, (sale_id, product_id))
        already_returned = results[0]["returned_qty"] if results else 0

        returnable = original_qty - already_returned
        return max(0, returnable)

    def create_return(
        self,
        invoice_number: str,
        items: List[dict],
        reason: str,
        user_id: int,
        customer_name: str = "",
        customer_phone: Optional[str] = None,
    ) -> Return:
        """
        Create a new return record.

        Args:
            invoice_number: Original invoice number
            items: List of dicts with {product_id, quantity, condition, return_reason}
            reason: Overall return reason
            user_id: Requesting user ID
            customer_name: Customer name
            customer_phone: Customer phone

        Returns:
            Return object (not yet saved to database)
        """
        # Find original sale
        original_sale = self.find_original_sale(invoice_number)
        if not original_sale:
            raise ValueError(f"Original sale not found: {invoice_number}")

        # Create return object
        invoice_rows = self.db.execute_query(
            "SELECT id, invoice_number FROM invoices WHERE invoice_number = ? LIMIT 1",
            (invoice_number,),
        )
        if not invoice_rows:
            raise ValueError(f"Invoice not found: {invoice_number}")
        if original_sale.id is None:
            raise ValueError(f"Original sale has no ID: {invoice_number}")
        return_obj = Return(
            return_number=self._generate_return_number(),
            original_sale_id=original_sale.id,
            original_invoice_id=invoice_rows[0]["id"],
            original_invoice_number=invoice_rows[0]["invoice_number"],
            customer_name=customer_name or original_sale.customer_name,
            customer_phone=customer_phone or original_sale.customer_phone,
            customer_id=original_sale.customer_id,
            vehicle_id=original_sale.vehicle_id,
            user_id=user_id,
            reason=reason,
            status="PENDING",
            external_id=str(uuid.uuid4()),
        )

        # Add return items with validation
        for item_data in items:
            product_id = item_data["product_id"]
            quantity = item_data["quantity"]
            condition = item_data.get("condition", "GOOD")
            item_reason = item_data.get("return_reason")

            # Find original item in sale
            original_item = None
            for sale_item in original_sale.items:
                if sale_item.product_id == product_id:
                    original_item = sale_item
                    break

            if not original_item:
                raise ValueError(
                    f"Product not found in original sale: {product_id}"
                )

            # Check returnable quantity
            returnable = self.calculate_returnable_quantity(
                product_id, original_item.quantity, original_sale.id
            )

            if quantity > returnable:
                raise ValueError(
                    f"Cannot return {quantity} of product {product_id}. "
                    f"Only {returnable} returnable (sold {original_item.quantity}, "
                    f"already returned)"
                )

            # Create return item
            return_item = ReturnItem(
                sale_item_id=original_item.id,
                product_id=product_id,
                product_name=original_item.product_name,
                part_no=original_item.part_no,
                brand=original_item.brand,
                vehicle_make=original_item.vehicle_make,
                vehicle_model=original_item.vehicle_model,
                quantity=quantity,
                unit_price=original_item.unit_price,
                vat_rate=original_item.vat_rate,
                condition=condition,
                return_reason=item_reason,
            )

            return_obj.add_item(return_item)

        logger.info(
            f"Return created: {return_obj.return_number} for invoice {invoice_number}"
        )
        return return_obj

    def save_return(self, return_obj: Return) -> int:
        """
        Save return to database.

        Args:
            return_obj: Return object

        Returns:
            Return ID
        """
        try:
            # Insert return
            return_query = """
                INSERT INTO returns (return_number, original_sale_id, original_invoice_id,
                                    customer_id, vehicle_id, customer_name, customer_phone, user_id,
                                    return_type, refund_method, subtotal, vat_amount, 
                                    total_refund, reason, status, external_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """

            params = (
                return_obj.return_number,
                return_obj.original_sale_id,
                return_obj.original_invoice_id,
                return_obj.customer_id,
                return_obj.vehicle_id,
                return_obj.customer_name,
                return_obj.customer_phone,
                return_obj.user_id,
                return_obj.return_type,
                return_obj.refund_method,
                return_obj.subtotal,
                return_obj.vat_amount,
                return_obj.total_refund,
                return_obj.reason,
                return_obj.status,
                return_obj.external_id,
            )

            with self.db.transaction() as conn:
                cursor = conn.execute(return_query, params)
                return_obj.id = cursor.lastrowid
                for item in return_obj.items:
                    conn.execute(
                        "INSERT INTO return_items (return_id, sale_item_id, product_id, quantity, unit_price, vat_rate, line_total, condition, return_reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            return_obj.id,
                            item.sale_item_id,
                            item.product_id,
                            item.quantity,
                            item.unit_price,
                            item.vat_rate,
                            item.line_total,
                            item.condition,
                            item.return_reason,
                        ),
                    )

            logger.info(
                f"Return saved: {return_obj.return_number} (ID: {return_obj.id})"
            )
            self.sync.enqueue(
                "RETURN",
                return_obj.id,
                "CREATE",
                json.dumps(return_obj.to_dict()),
            )
            self.sync.request_background_sync()
            return return_obj.id
        except Exception as e:
            logger.error(f"Failed to save return: {e}")
            raise

    def approve_return(self, return_id: int, approved_by_user_id: int) -> bool:
        """
        Approve a return (authority to proceed with refund).

        Args:
            return_id: Return ID
            approved_by_user_id: User ID doing the approval

        Returns:
            True if successful
        """
        # Check authorization
        if not self.permission_service.has_permission(
            approved_by_user_id, "APPROVE_RETURN"
        ):
            raise PermissionError(
                f"User {approved_by_user_id} cannot approve returns"
            )

        try:
            query = """
                UPDATE returns 
                SET status = 'APPROVED', authorized_by = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """

            self.db.execute_update(query, (approved_by_user_id, return_id))
            logger.info(f"Return approved: {return_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to approve return: {e}")
            raise

    def process_return(self, return_id: int, user_id: int) -> bool:
        """
        Process the return - update inventory based on item conditions.

        Args:
            return_id: Return ID
            user_id: User ID processing the return

        Returns:
            True if successful
        """
        return_obj = self.get_return_by_id(return_id)
        if not return_obj:
            raise ValueError(f"Return not found: {return_id}")

        if return_obj.status != "APPROVED":
            raise ValueError(
                f"Return must be approved before processing (status: {return_obj.status})"
            )

        try:
            with self.db.transaction() as conn:
                for item in return_obj.items:
                    product = conn.execute(
                        "SELECT quantity_on_hand FROM products WHERE id=?",
                        (item.product_id,),
                    ).fetchone()
                    if product is None:
                        raise ValueError(
                            f"Product not found: {item.product_id}"
                        )
                    previous = int(product[0])
                    restored = item.condition in ("GOOD", "WRONG_PART")
                    new_quantity = (
                        previous + item.quantity if restored else previous
                    )
                    conn.execute(
                        "UPDATE products SET quantity_on_hand=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        (new_quantity, item.product_id),
                    )
                    conn.execute(
                        "INSERT INTO stock_movements (product_id, movement_type, quantity, previous_quantity, new_quantity, reference, user_id, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            item.product_id,
                            "RETURN" if restored else "DAMAGE",
                            item.quantity if restored else 0,
                            previous,
                            new_quantity,
                            f"RETURN-{return_id}",
                            user_id,
                            f"Returned {item.condition}: {item.return_reason or ''}",
                        ),
                    )
                conn.execute(
                    "UPDATE returns SET status='COMPLETED', updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='APPROVED'",
                    (return_id,),
                )
            logger.info(f"Return processed: {return_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to process return: {e}")
            raise

    def process_refund(
        self, return_id: int, refund_method: str, user_id: int
    ) -> int:
        """
        Process refund for a return.

        Args:
            return_id: Return ID
            refund_method: CASH_USD, CASH_ZIG, ECOCASH, CARD_REFUND, STORE_CREDIT
            user_id: User processing refund

        Returns:
            Refund ID
        """
        return_obj = self.get_return_by_id(return_id)
        if not return_obj:
            raise ValueError(f"Return not found: {return_id}")

        # Check permission
        if not self.permission_service.has_permission(
            user_id, "PROCESS_REFUND"
        ):
            raise PermissionError(f"User {user_id} cannot process refunds")

        # Check large refund threshold
        if (
            return_obj.total_refund
            > self.RETURN_LIMITS["LARGE_REFUND_THRESHOLD_USD"]
        ):
            if not self.permission_service.has_permission(
                user_id, "PROCESS_LARGE_REFUND"
            ):
                raise PermissionError(
                    f"Large refund ({return_obj.total_refund}) requires PROCESS_LARGE_REFUND permission"
                )

        try:
            if self.db.execute_query(
                "SELECT 1 FROM refunds WHERE return_id=? LIMIT 1", (return_id,)
            ):
                raise ValueError(
                    f"Refund already processed for return {return_id}"
                )
            # Create refund record
            refund = Refund(
                return_id=return_id,
                refund_amount=return_obj.total_refund,
                refund_method=refund_method,
                currency={"CASH_USD": "USD", "CASH_ZIG": "ZiG"}.get(
                    refund_method, "ZWL"
                ),
                status="COMPLETED",
                processed_by=user_id,
            )

            # Insert refund
            refund_query = """
                INSERT INTO refunds (return_id, refund_amount, refund_method, currency, 
                                    original_payment_method, status, processed_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """

            params = (
                return_id,
                refund.refund_amount,
                refund.refund_method,
                refund.currency,
                None,  # original_payment_method - could be looked up
                refund.status,
                user_id,
            )

            with self.db.transaction() as conn:
                refund.id = conn.execute(refund_query, params).lastrowid
                conn.execute(
                    "UPDATE returns SET refund_method=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (refund_method, return_id),
                )

            logger.info(
                f"Refund processed: {refund.id} for return {return_id}"
            )
            self.sync.enqueue(
                "REFUND", refund.id, "CREATE", json.dumps(refund.to_dict())
            )
            self.sync.request_background_sync()
            return refund.id
        except Exception as e:
            logger.error(f"Failed to process refund: {e}")
            raise

    def get_return_by_id(self, return_id: int) -> Optional[Return]:
        """Get return by ID."""
        query = "SELECT * FROM returns WHERE id = ?"
        results = self.db.execute_query(query, (return_id,))

        if not results:
            return None

        return_obj = self._row_to_return(results[0])

        # Load return items
        items_query = "SELECT * FROM return_items WHERE return_id = ?"
        items_results = self.db.execute_query(items_query, (return_id,))

        for item_row in items_results:
            item = ReturnItem(
                id=item_row["id"],
                return_id=item_row["return_id"],
                product_id=item_row["product_id"],
                quantity=item_row["quantity"],
                unit_price=item_row["unit_price"],
                vat_rate=item_row["vat_rate"],
                line_total=item_row["line_total"],
                condition=item_row["condition"],
                return_reason=item_row["return_reason"],
            )
            return_obj.items.append(item)

        return return_obj

    def get_returns_by_invoice(self, invoice_number: str) -> List[Return]:
        """Get all returns for an invoice."""
        query = "SELECT * FROM returns WHERE original_invoice_number = ? ORDER BY created_at DESC"
        results = self.db.execute_query(query, (invoice_number,))

        returns = []
        for row in results:
            return_obj = self._row_to_return(row)
            returns.append(return_obj)

        return returns

    def search_returns(self, search_term: str) -> List[Return]:
        """Search returns by return number, invoice number, or customer name."""
        query = """
            SELECT * FROM returns 
            WHERE return_number LIKE ? OR original_invoice_number LIKE ? 
               OR customer_name LIKE ? OR customer_phone LIKE ?
            ORDER BY created_at DESC
        """

        pattern = f"%{search_term}%"
        results = self.db.execute_query(
            query, (pattern, pattern, pattern, pattern)
        )
        return [self._row_to_return(row) for row in results]

    @staticmethod
    def _generate_return_number() -> str:
        """Generate unique return number."""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        unique_id = str(uuid.uuid4())[:8].upper()
        return f"RET-{timestamp}-{unique_id}"

    @staticmethod
    def _row_to_return(row) -> Return:
        """Convert database row to Return object."""
        return Return(
            id=row["id"],
            return_number=row["return_number"],
            original_sale_id=row["original_sale_id"],
            original_invoice_id=row["original_invoice_id"],
            original_invoice_number=row["original_invoice_number"],
            customer_name=row["customer_name"],
            customer_phone=row["customer_phone"],
            user_id=row["user_id"],
            authorized_by=row["authorized_by"],
            return_type=row["return_type"],
            refund_method=row["refund_method"],
            subtotal=row["subtotal"],
            vat_amount=row["vat_amount"],
            total_refund=row["total_refund"],
            reason=row["reason"],
            status=row["status"],
            external_id=row["external_id"],
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
