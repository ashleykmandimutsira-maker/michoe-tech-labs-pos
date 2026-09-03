"""
Returns and Refunds models for Motor Spares POS.
PHASE 2: Returns & Refunds module.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List


@dataclass
class ReturnItem:
    """
    Individual item being returned.
    """

    id: Optional[int] = None
    return_id: Optional[int] = None
    sale_item_id: Optional[int] = None
    product_id: int = 0
    product_name: str = ""
    product_barcode: Optional[str] = None
    part_no: str = ""
    brand: str = ""
    vehicle_make: Optional[str] = None
    vehicle_model: Optional[str] = None
    quantity: int = 0
    unit_price: float = 0.0
    vat_rate: float = 15.0
    line_total: float = 0.0
    condition: str = "GOOD"  # GOOD, DAMAGED, DEFECTIVE, WRONG_PART, USED
    return_reason: Optional[str] = None
    created_at: Optional[datetime] = None

    def calculate_total(self) -> float:
        """Calculate total for this return item."""
        self.line_total = self.quantity * self.unit_price
        return self.line_total

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "return_id": self.return_id,
            "sale_item_id": self.sale_item_id,
            "product_id": self.product_id,
            "product_name": self.product_name,
            "part_no": self.part_no,
            "brand": self.brand,
            "vehicle": f"{self.vehicle_make} {self.vehicle_model}".strip(),
            "quantity": self.quantity,
            "unit_price": self.unit_price,
            "vat_rate": self.vat_rate,
            "line_total": self.line_total,
            "condition": self.condition,
            "return_reason": self.return_reason,
            "created_at": (
                self.created_at.isoformat() if self.created_at else None
            ),
        }


@dataclass
class Refund:
    """
    Refund or credit for a return.
    """

    id: Optional[int] = None
    return_id: Optional[int] = None
    refund_amount: float = 0.0
    refund_method: str = (
        ""  # CASH_USD, CASH_ZIG, ECOCASH, STORE_CREDIT, CARD_REFUND
    )
    currency: str = "ZWL"
    exchange_rate: float = 1.0
    original_payment_method: Optional[str] = None
    status: str = "PENDING"  # PENDING, APPROVED, COMPLETED, FAILED
    processed_by: Optional[int] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "return_id": self.return_id,
            "refund_amount": self.refund_amount,
            "refund_method": self.refund_method,
            "currency": self.currency,
            "exchange_rate": self.exchange_rate,
            "original_payment_method": self.original_payment_method,
            "status": self.status,
            "processed_by": self.processed_by,
            "notes": self.notes,
            "created_at": (
                self.created_at.isoformat() if self.created_at else None
            ),
            "updated_at": (
                self.updated_at.isoformat() if self.updated_at else None
            ),
        }


@dataclass
class Return:
    """
    Complete return transaction.
    Links back to original sale/invoice.
    """

    id: Optional[int] = None
    return_number: str = ""
    original_sale_id: int = 0
    original_invoice_id: Optional[int] = None
    original_invoice_number: str = ""
    customer_id: Optional[int] = None
    vehicle_id: Optional[int] = None
    customer_name: str = ""
    customer_phone: Optional[str] = None
    user_id: int = 0
    authorized_by: Optional[int] = None
    authorizer_name: Optional[str] = None
    return_type: str = "RETURN"  # RETURN, EXCHANGE, STORE_CREDIT
    refund_method: str = ""
    items: List[ReturnItem] = field(default_factory=list)
    refund: Optional[Refund] = None
    subtotal: float = 0.0
    vat_amount: float = 0.0
    total_refund: float = 0.0
    reason: Optional[str] = None
    status: str = (
        "PENDING"  # PENDING, APPROVED, COMPLETED, REJECTED, CANCELLED
    )
    external_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def add_item(self, item: ReturnItem):
        """Add return item and recalculate totals."""
        item.calculate_total()
        self.items.append(item)
        self.recalculate_totals()

    def recalculate_totals(self):
        """Recalculate return totals."""
        self.subtotal = sum(item.line_total for item in self.items)
        self.vat_amount = sum(
            (item.quantity * item.unit_price * item.vat_rate / 100)
            for item in self.items
        )
        self.total_refund = self.subtotal + self.vat_amount

    def approve(self, approved_by_user_id: int):
        """Approve the return."""
        self.status = "APPROVED"
        self.authorized_by = approved_by_user_id
        self.updated_at = datetime.now()

    def complete(self):
        """Mark return as completed."""
        self.status = "COMPLETED"
        self.updated_at = datetime.now()

    def reject(self):
        """Reject the return."""
        self.status = "REJECTED"
        self.updated_at = datetime.now()

    def void(self):
        """Void the return."""
        self.status = "CANCELLED"
        self.updated_at = datetime.now()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "return_number": self.return_number,
            "original_sale_id": self.original_sale_id,
            "original_invoice_id": self.original_invoice_id,
            "original_invoice_number": self.original_invoice_number,
            "customer_id": self.customer_id,
            "customer_name": self.customer_name,
            "customer_phone": self.customer_phone,
            "user_id": self.user_id,
            "authorized_by": self.authorized_by,
            "authorizer_name": self.authorizer_name,
            "return_type": self.return_type,
            "refund_method": self.refund_method,
            "items": [item.to_dict() for item in self.items],
            "refund": self.refund.to_dict() if self.refund else None,
            "subtotal": self.subtotal,
            "vat_amount": self.vat_amount,
            "total_refund": self.total_refund,
            "reason": self.reason,
            "status": self.status,
            "external_id": self.external_id,
            "created_at": (
                self.created_at.isoformat() if self.created_at else None
            ),
            "updated_at": (
                self.updated_at.isoformat() if self.updated_at else None
            ),
        }
