"""
Product model for Motor Spares POS.
Represents a product/spare part with all its attributes.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Category:
    """Product category."""
    id: Optional[int] = None
    name: str = ""
    description: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class VehicleModel:
    """Vehicle model information."""
    id: Optional[int] = None
    make: str = ""  # Toyota, Honda, Ford, etc.
    model: str = ""  # Corolla, Civic, Ranger, etc.
    year_from: Optional[int] = None
    year_to: Optional[int] = None
    created_at: Optional[datetime] = None


@dataclass
class Product:
    """
    Motor spares product/inventory item.
    
    Attributes:
        id: Product ID (auto-generated)
        barcode: Barcode string (unique, can be None)
        part_no: Part number (unique)
        description: Product description
        brand: Brand/manufacturer
        category_id: Foreign key to category
        vehicle_make: Vehicle make (Toyota, Honda, etc.)
        vehicle_model: Vehicle model (Corolla, Civic, etc.)
        cost_price: Cost to business
        selling_price: Retail price
        currency: Currency code (ZWL, USD, etc.)
        quantity_on_hand: Current stock level
        reorder_level: Stock level that triggers warning
        vat_rate: VAT percentage (typically 15%)
        active: Is product active
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """
    id: Optional[int] = None
    barcode: Optional[str] = None
    part_no: str = ""
    oem_number: Optional[str] = None
    description: str = ""
    brand: str = ""
    category_id: Optional[int] = None
    vehicle_make: Optional[str] = None
    vehicle_model: Optional[str] = None
    vehicle_year_from: Optional[int] = None
    vehicle_year_to: Optional[int] = None
    cost_price: float = 0.0
    selling_price: float = 0.0
    currency: str = "ZWL"
    quantity_on_hand: int = 0
    reorder_level: int = 5
    vat_rate: float = 15.0
    active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def is_in_stock(self) -> bool:
        """Check if product has stock available."""
        return self.quantity_on_hand > 0

    def is_low_stock(self) -> bool:
        """Check if product stock is below reorder level."""
        return self.quantity_on_hand <= self.reorder_level

    def is_out_of_stock(self) -> bool:
        """Check if product is out of stock."""
        return self.quantity_on_hand == 0

    def get_margin(self) -> float:
        """Calculate profit margin."""
        if self.cost_price == 0:
            return 0.0
        return ((self.selling_price - self.cost_price) / self.selling_price) * 100

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'id': self.id,
            'barcode': self.barcode,
            'part_no': self.part_no,
            'oem_number': self.oem_number,
            'description': self.description,
            'brand': self.brand,
            'category_id': self.category_id,
            'vehicle_make': self.vehicle_make,
            'vehicle_model': self.vehicle_model,
            'vehicle_year_from': self.vehicle_year_from,
            'vehicle_year_to': self.vehicle_year_to,
            'cost_price': self.cost_price,
            'selling_price': self.selling_price,
            'currency': self.currency,
            'quantity_on_hand': self.quantity_on_hand,
            'reorder_level': self.reorder_level,
            'vat_rate': self.vat_rate,
            'active': self.active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


@dataclass
class StockMovement:
    """
    Record of a stock movement/transaction.
    Used for audit trail and inventory tracking.
    
    Attributes:
        id: Movement ID
        product_id: Product that was moved
        movement_type: Type of movement (PURCHASE, SALE, RETURN, ADJUSTMENT, DAMAGE, TRANSFER, VOID)
        quantity: Amount moved
        previous_quantity: Stock before movement
        new_quantity: Stock after movement
        reference: Reference number (e.g., invoice/PO number)
        user_id: User who made the movement
        notes: Additional notes
        created_at: Movement timestamp
    """
    id: Optional[int] = None
    product_id: int = 0
    movement_type: str = ""  # PURCHASE, SALE, RETURN, ADJUSTMENT, DAMAGE, TRANSFER, VOID
    quantity: int = 0
    previous_quantity: int = 0
    new_quantity: int = 0
    reference: Optional[str] = None
    user_id: Optional[int] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None

    VALID_TYPES = {
        'PURCHASE': 'Stock received from supplier',
        'SALE': 'Sold to customer',
        'RETURN': 'Returned by customer',
        'ADJUSTMENT': 'Manual adjustment',
        'DAMAGE': 'Damaged/destroyed',
        'TRANSFER': 'Transferred to another location',
        'VOID': 'Voided transaction'
    }

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            'id': self.id,
            'product_id': self.product_id,
            'movement_type': self.movement_type,
            'quantity': self.quantity,
            'previous_quantity': self.previous_quantity,
            'new_quantity': self.new_quantity,
            'reference': self.reference,
            'user_id': self.user_id,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
