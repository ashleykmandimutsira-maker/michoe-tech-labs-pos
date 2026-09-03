"""
Sales, Invoice, and Payment models for Motor Spares POS.
PHASE 2: Sales management.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List


@dataclass
class SaleItem:
    """
    Individual item in a sale.
    """
    id: Optional[int] = None
    sale_id: Optional[int] = None
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
    created_at: Optional[datetime] = None

    def calculate_total(self) -> float:
        """Calculate total for this line."""
        self.line_total = self.quantity * self.unit_price
        return self.line_total

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'sale_id': self.sale_id,
            'product_id': self.product_id,
            'product_name': self.product_name,
            'part_no': self.part_no,
            'brand': self.brand,
            'vehicle': f"{self.vehicle_make} {self.vehicle_model}".strip(),
            'quantity': self.quantity,
            'unit_price': self.unit_price,
            'vat_rate': self.vat_rate,
            'line_total': self.line_total,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


@dataclass
class Payment:
    """
    Payment for a sale.
    Supports multiple payment methods.
    """
    id: Optional[int] = None
    sale_id: Optional[int] = None
    payment_method: str = ""  # CASH_USD, CASH_ZIG, ECOCASH, CARD, STORE_CREDIT
    currency: str = "ZWL"
    amount: float = 0.0
    tendered: Optional[float] = None
    change: Optional[float] = 0.0
    exchange_rate: float = 1.0
    status: str = "COMPLETED"
    created_at: Optional[datetime] = None

    def calculate_change(self):
        """Calculate change for cash payments."""
        if self.tendered is not None and self.amount > 0:
            self.change = max(0, self.tendered - self.amount)
        return self.change

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'sale_id': self.sale_id,
            'payment_method': self.payment_method,
            'currency': self.currency,
            'amount': self.amount,
            'tendered': self.tendered,
            'change': self.change,
            'exchange_rate': self.exchange_rate,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


@dataclass
class Sale:
    """
    Complete sale transaction.
    """
    id: Optional[int] = None
    invoice_number: str = ""
    customer_id: Optional[int] = None
    customer_name: str = ""
    customer_phone: Optional[str] = None
    customer_email: Optional[str] = None
    customer_city: Optional[str] = None
    vehicle_id: Optional[int] = None
    vehicle_make: Optional[str] = None
    vehicle_model: Optional[str] = None
    vehicle_registration: Optional[str] = None
    user_id: int = 0
    cashier_name: str = ""
    items: List[SaleItem] = field(default_factory=list)
    payments: List[Payment] = field(default_factory=list)
    subtotal: float = 0.0
    vat_amount: float = 0.0
    discount_amount: float = 0.0
    total: float = 0.0
    status: str = "COMPLETED"
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def add_item(self, item: SaleItem):
        """Add item to sale and recalculate totals."""
        item.calculate_total()
        self.items.append(item)
        self.recalculate_totals()

    def add_payment(self, payment: Payment):
        """Add payment to sale."""
        self.payments.append(payment)

    def recalculate_totals(self):
        """Recalculate sale totals."""
        self.subtotal = sum(item.quantity * item.unit_price for item in self.items)
        self.vat_amount = sum(
            (item.quantity * item.unit_price * item.vat_rate / 100)
            for item in self.items
        )
        self.total = self.subtotal + self.vat_amount - self.discount_amount

    def apply_discount(self, discount: float):
        """Apply discount to sale."""
        self.discount_amount = discount
        self.recalculate_totals()

    def get_total_paid(self) -> float:
        """Get total amount paid."""
        return sum(p.amount for p in self.payments)

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'invoice_number': self.invoice_number,
            'customer_id': self.customer_id,
            'customer_name': self.customer_name,
            'customer_phone': self.customer_phone,
            'customer_email': self.customer_email,
            'customer_city': self.customer_city,
            'vehicle_id': self.vehicle_id,
            'vehicle_make': self.vehicle_make,
            'vehicle_model': self.vehicle_model,
            'vehicle_registration': self.vehicle_registration,
            'user_id': self.user_id,
            'cashier_name': self.cashier_name,
            'items': [item.to_dict() for item in self.items],
            'payments': [p.to_dict() for p in self.payments],
            'subtotal': self.subtotal,
            'vat_amount': self.vat_amount,
            'discount_amount': self.discount_amount,
            'total': self.total,
            'status': self.status,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


@dataclass
class Invoice:
    """
    Formal invoice record for a sale.
    """
    id: Optional[int] = None
    invoice_number: str = ""
    sale_id: int = 0
    customer_name: str = ""
    customer_phone: Optional[str] = None
    customer_email: Optional[str] = None
    customer_city: Optional[str] = None
    customer_id: Optional[int] = None
    vehicle_id: Optional[int] = None
    vehicle_make: Optional[str] = None
    vehicle_model: Optional[str] = None
    vehicle_registration: Optional[str] = None
    subtotal: float = 0.0
    vat_amount: float = 0.0
    total: float = 0.0
    payment_method: str = ""
    status: str = "ISSUED"  # ISSUED, PAID, CANCELLED
    created_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'invoice_number': self.invoice_number,
            'sale_id': self.sale_id,
            'customer_name': self.customer_name,
            'customer_phone': self.customer_phone,
            'customer_email': self.customer_email,
            'customer_city': self.customer_city,
            'customer_id': self.customer_id,
            'vehicle_make': self.vehicle_make,
            'vehicle_model': self.vehicle_model,
            'vehicle_registration': self.vehicle_registration,
            'subtotal': self.subtotal,
            'vat_amount': self.vat_amount,
            'total': self.total,
            'payment_method': self.payment_method,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
