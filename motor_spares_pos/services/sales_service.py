"""
Sales and invoice management service.
PHASE 2: Sales transactions.
"""

import logging
from typing import Optional, List
from datetime import datetime
import uuid

from database.db import get_database_manager
from models.sale import Sale, SaleItem, Payment, Invoice
from models.product import Product
from services.product_service import ProductService
from services.inventory_service import InventoryService
from services.sync_service import SyncService
from services.permission_service import PermissionService
from services.audit_service import AuditService
import json

logger = logging.getLogger(__name__)


class SalesService:
    """Service for managing sales transactions and invoices."""

    def __init__(self):
        """Initialize sales service."""
        self.db = get_database_manager()
        self.product_service = ProductService()
        self.inventory_service = InventoryService()
        self.sync = SyncService()

    def create_sale(self, customer_name: str = "", customer_phone: Optional[str] = None,
                   customer_id: Optional[int] = None, customer_email: Optional[str] = None,
                   customer_city: Optional[str] = None,
                   vehicle_make: Optional[str] = None, vehicle_model: Optional[str] = None,
                   vehicle_registration: Optional[str] = None,
                   user_id: int = 0, cashier_name: str = "", vehicle_id: Optional[int] = None) -> Sale:
        """
        Create a new sale transaction.
        
        Args:
            customer_name: Customer name
            customer_phone: Customer phone number
            user_id: Cashier user ID
            cashier_name: Cashier name
            
        Returns:
            New Sale object
        """
        sale = Sale(
            customer_name=customer_name,
            customer_phone=customer_phone,
            customer_id=customer_id,
            customer_email=customer_email,
            customer_city=customer_city,
            vehicle_id=vehicle_id,
            vehicle_make=vehicle_make,
            vehicle_model=vehicle_model,
            vehicle_registration=vehicle_registration,
            user_id=user_id,
            cashier_name=cashier_name,
        )
        
        logger.info(f"New sale started for customer: {customer_name}")
        return sale

    def add_item_to_sale(self, sale: Sale, product_id: int, quantity: int, unit_price: Optional[float] = None) -> SaleItem:
        """
        Add an item to a sale.
        
        Args:
            sale: Sale object
            product_id: Product ID
            quantity: Quantity to sell
            unit_price: Price per unit (if None, uses product's sell price)
            
        Returns:
            SaleItem added to sale
        """
        # Get product details
        product = self.product_service.get_product_by_id(product_id)
        if not product:
            raise ValueError(f"Product not found: {product_id}")
        
        # Check stock
        if product.quantity_on_hand < quantity:
            raise ValueError(
                f"Insufficient stock for {product.description}. "
                f"Available: {product.quantity_on_hand}, Requested: {quantity}"
            )
        
        # Use provided price or product's sell price
        if unit_price is None:
            unit_price = product.selling_price
        
        # Create sale item
        item = SaleItem(
            product_id=product_id,
            product_name=product.description,
            product_barcode=product.barcode,
            part_no=product.part_no,
            brand=product.brand,
            vehicle_make=product.vehicle_make,
            vehicle_model=product.vehicle_model,
            quantity=quantity,
            unit_price=unit_price,
            vat_rate=product.vat_rate,
        )
        
        # Add to sale
        sale.add_item(item)
        
        logger.info(f"Item added to sale: {product.description} (qty: {quantity})")
        return item

    def apply_discount(self, sale: Sale, discount_amount: float):
        """
        Apply a discount to the sale.
        
        Args:
            sale: Sale object
            discount_amount: Discount amount in base currency
        """
        sale.apply_discount(discount_amount)
        logger.info(f"Discount applied to sale: {discount_amount}")

    def add_payment(self, sale: Sale, payment_method: str, amount: float, 
                   currency: str = "ZWL", tendered: Optional[float] = None) -> Payment:
        """
        Record a payment for the sale.
        
        Args:
            sale: Sale object
            payment_method: Payment method (CASH_USD, CASH_ZIG, ECOCASH, CARD, STORE_CREDIT)
            amount: Amount to pay
            currency: Currency code
            tendered: Amount tendered (for cash)
            
        Returns:
            Payment object
        """
        payment = Payment(
            payment_method=payment_method,
            currency=currency,
            amount=amount,
            tendered=tendered,
        )
        
        payment.calculate_change()
        sale.add_payment(payment)
        
        logger.info(f"Payment added to sale: {amount} {currency} ({payment_method})")
        return payment

    def validate_payments(self, sale: Sale) -> None:
        """Reject missing, invalid, or short split tenders before persisting a sale."""
        if not sale.payments:
            raise ValueError("Cannot complete sale with no payments")
        paid = sum(float(payment.amount) for payment in sale.payments)
        if any(float(payment.amount) <= 0 for payment in sale.payments):
            raise ValueError("Each payment amount must be greater than zero")
        if round(paid + 1e-9, 2) < round(float(sale.total), 2):
            raise ValueError(f"Payment is short by {sale.total - paid:.2f}")

    def complete_sale(self, sale: Sale) -> int:
        """
        Complete a sale and save to database.
        Updates inventory, creates invoice, and syncs.
        
        Args:
            sale: Sale object with items and payments
            
        Returns:
            Sale ID of completed sale
        """
        if not sale.items:
            raise ValueError("Cannot complete sale with no items")
        
        sale.status = "COMPLETED"
        sale.recalculate_totals()
        self.validate_payments(sale)
        
        # Generate invoice number
        invoice_number = self._generate_invoice_number()
        sale.invoice_number = invoice_number
        
        try:
            # Insert sale
            sale_query = """
                INSERT INTO sales (invoice_number, customer_id, customer_name, customer_phone, customer_email, customer_city, vehicle_id,
                                  vehicle_make, vehicle_model, vehicle_registration, user_id, cashier_name,
                                  subtotal, vat_amount, discount_amount, total, status, notes, quotation_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """

            with self.db.transaction() as conn:
                # If cashier provided customer details but no existing customer id, find or create within the transaction
                if not sale.customer_id and sale.customer_name:
                    try:
                        sale.customer_id = self._find_or_create_customer_tx(
                            conn,
                            sale.customer_name,
                            sale.customer_phone,
                            sale.customer_email,
                            sale.vehicle_make,
                            sale.vehicle_model,
                            sale.vehicle_registration,
                            sale.customer_city,
                        )
                    except Exception as e:
                        logger.exception("Failed to find or create customer during sale completion: %s", e)
                        raise

                params = (
                    invoice_number,
                    sale.customer_id,
                    sale.customer_name,
                    sale.customer_phone,
                    sale.customer_email,
                    sale.customer_city,
                    sale.vehicle_id,
                    sale.vehicle_make,
                    sale.vehicle_model,
                    sale.vehicle_registration,
                    sale.user_id,
                    sale.cashier_name,
                    sale.subtotal,
                    sale.vat_amount,
                    sale.discount_amount,
                    sale.total,
                    sale.status,
                    sale.notes,
                    getattr(sale, '_quotation_id', None),
                )

                sale.id = conn.execute(sale_query, params).lastrowid

                # Insert sale items and deduct stock on the same connection.
                for item in sale.items:
                    item_query = """
                        INSERT INTO sale_items (sale_id, product_id, quantity, unit_price, vat_rate, line_total)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """
                    item_params = (
                        sale.id, item.product_id, item.quantity, item.unit_price,
                        item.vat_rate, item.line_total,
                    )
                    conn.execute(item_query, item_params)
                    product = conn.execute("SELECT part_no, quantity_on_hand FROM products WHERE id=?", (item.product_id,)).fetchone()
                    if product is None:
                        raise ValueError(f"Product not found: {item.product_id}")
                    previous = int(product[1])
                    if item.quantity > previous:
                        raise ValueError(f"Insufficient stock for product {product[0]}. Available: {previous}, Requested: {item.quantity}")
                    new_quantity = previous - item.quantity
                    conn.execute("UPDATE products SET quantity_on_hand=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (new_quantity, item.product_id))
                    conn.execute("INSERT INTO stock_movements (product_id,movement_type,quantity,previous_quantity,new_quantity,reference,user_id,notes) VALUES (?,?,?,?,?,?,?,?)", (item.product_id, 'SALE', item.quantity, previous, new_quantity, invoice_number, sale.user_id, f"Invoice: {invoice_number}"))

                # Insert payments in the same transaction.
                for payment in sale.payments:
                    payment_query = """
                        INSERT INTO payments (sale_id, payment_method, currency, amount,
                                             tendered, change, exchange_rate, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """
                    payment_params = (
                        sale.id, payment.payment_method, payment.currency, payment.amount,
                        payment.tendered, payment.change, payment.exchange_rate, payment.status,
                    )
                    conn.execute(payment_query, payment_params)

                # Create invoice record in the same transaction.
                invoice = Invoice(
                invoice_number=invoice_number,
                sale_id=sale.id,
                customer_id=sale.customer_id,
                customer_name=sale.customer_name,
                customer_phone=sale.customer_phone,
                customer_email=sale.customer_email,
                customer_city=sale.customer_city,
                vehicle_id=sale.vehicle_id,
                vehicle_make=sale.vehicle_make,
                vehicle_model=sale.vehicle_model,
                vehicle_registration=sale.vehicle_registration,
                subtotal=sale.subtotal,
                vat_amount=sale.vat_amount,
                total=sale.total,
                payment_method=sale.payments[0].payment_method if sale.payments else "",
                status="PAID",
            )
            
                invoice_query = """
                    INSERT INTO invoices (invoice_number, sale_id, customer_id, customer_name, customer_phone, customer_email, customer_city, vehicle_id,
                                         vehicle_make, vehicle_model, vehicle_registration, subtotal, vat_amount, total, payment_method, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
            
                invoice_params = (
                invoice.invoice_number,
                sale.id,
                invoice.customer_id,
                invoice.customer_name,
                invoice.customer_phone,
                invoice.customer_email,
                invoice.customer_city,
                invoice.vehicle_id,
                invoice.vehicle_make,
                invoice.vehicle_model,
                invoice.vehicle_registration,
                invoice.subtotal,
                invoice.vat_amount,
                invoice.total,
                invoice.payment_method,
                invoice.status,
            )
            
                conn.execute(invoice_query, invoice_params)
            
            logger.info(f"Sale completed: {invoice_number} (ID: {sale.id})")
            self.sync.enqueue("SALE", sale.id, "CREATE", json.dumps(sale.to_dict()))
            self.sync.request_background_sync()
            return sale.id
        
        except Exception as e:
            logger.error(f"Failed to complete sale: {e}")
            raise

    def hold_sale(self, cart: dict, customer: Optional[dict], user_id: Optional[int]) -> dict:
        """Persist a POS cart for later resumption without touching inventory."""
        if not cart:
            raise ValueError("Cannot hold an empty cart")
        hold_number = f"HOLD-{uuid.uuid4().hex[:10].upper()}"
        with self.db.transaction() as conn:
            hold_id = conn.execute(
                "INSERT INTO held_sales(hold_number,customer_data,cart_data,user_id) VALUES(?,?,?,?)",
                (hold_number, json.dumps(customer or {}), json.dumps(cart), user_id),
            ).lastrowid
        return self.get_held_sale(hold_id)

    def list_held_sales(self) -> list[dict]:
        return [dict(row) for row in self.db.execute_query(
            "SELECT * FROM held_sales WHERE status='HELD' ORDER BY updated_at DESC, id DESC"
        )]

    def get_held_sale(self, hold_id: int) -> Optional[dict]:
        rows = self.db.execute_query("SELECT * FROM held_sales WHERE id=? AND status='HELD'", (hold_id,))
        if not rows:
            return None
        held = dict(rows[0])
        held['customer'] = json.loads(held.pop('customer_data') or '{}')
        held['cart'] = {int(product_id): item for product_id, item in json.loads(held.pop('cart_data')).items()}
        return held

    def release_held_sale(self, hold_id: int) -> Optional[dict]:
        held = self.get_held_sale(hold_id)
        if held:
            self.db.execute_update("UPDATE held_sales SET status='RESUMED', updated_at=CURRENT_TIMESTAMP WHERE id=?", (hold_id,))
        return held

    def create_quotation(self, cart: dict, customer: Optional[dict], user_id: Optional[int], vehicle_id: Optional[int] = None) -> dict:
        """Save a quotation snapshot that can be reprinted or converted later."""
        if not cart:
            raise ValueError("Cannot quote an empty cart")
        if user_id is not None:
            PermissionService().check_permission_or_raise(user_id, 'quotations.create')
        items = list(cart.values())
        subtotal = sum(float(item['quantity']) * float(item['unit_price']) for item in items)
        quote_number = f"QUOTE-{uuid.uuid4().hex[:10].upper()}"
        with self.db.transaction() as conn:
            quote_id = conn.execute(
                "INSERT INTO quotations(quote_number,customer_data,vehicle_id,user_id,subtotal,total) VALUES(?,?,?,?,?,?)",
                (quote_number, json.dumps(customer or {}), vehicle_id, user_id, subtotal, subtotal),
            ).lastrowid
            conn.executemany(
                "INSERT INTO quotation_items(quotation_id,product_id,part_no,description,brand,vehicle_make,vehicle_model,quantity,unit_price,line_total) VALUES(?,?,?,?,?,?,?,?,?,?)",
                [(quote_id, item['product_id'], item['part_no'], item['description'], item.get('brand'), item.get('vehicle_make'), item.get('vehicle_model'), int(item['quantity']), float(item['unit_price']), float(item['quantity']) * float(item['unit_price'])) for item in items],
            )
        quote = self.get_quotation(quote_id)
        AuditService().log_action('QUOTATION_CREATED', 'QUOTATION', quote_id, user_id)
        self.sync.enqueue('QUOTATION', quote_id, 'CREATE', json.dumps(quote))
        self.sync.request_background_sync()
        return quote

    def list_quotations(self, include_closed: bool = False, search_term: str = '') -> list[dict]:
        clauses = [] if include_closed else ["status IN ('DRAFT','ISSUED')"]
        params = []
        if search_term.strip():
            clauses.append("(quote_number LIKE ? OR customer_data LIKE ?)")
            params.extend([f"%{search_term.strip()}%", f"%{search_term.strip()}%"]) 
        query = "SELECT id FROM quotations" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY created_at DESC, id DESC"
        return [self.get_quotation(row['id']) for row in self.db.execute_query(query, tuple(params))]

    def get_quotation(self, quote_id: int) -> Optional[dict]:
        rows = self.db.execute_query("SELECT * FROM quotations WHERE id=?", (quote_id,))
        if not rows:
            return None
        quote = dict(rows[0]); quote['customer'] = json.loads(quote.pop('customer_data') or '{}')
        quote['items'] = [dict(row) for row in self.db.execute_query("SELECT * FROM quotation_items WHERE quotation_id=? ORDER BY id", (quote_id,))]
        return quote

    def sale_from_quotation(self, quote_id: int, user_id: int, cashier_name: str) -> Sale:
        quote = self.get_quotation(quote_id)
        PermissionService().check_permission_or_raise(user_id, 'quotations.convert')
        if not quote or quote['status'] not in ('DRAFT', 'ISSUED'):
            raise ValueError("Quotation is unavailable or already converted")
        customer = quote['customer']
        sale = self.create_sale(customer.get('name', ''), customer.get('phone'), customer.get('id'), customer.get('email'), customer.get('city'), customer.get('vehicle_make'), customer.get('vehicle_model'), customer.get('vehicle_registration'), user_id, cashier_name, quote.get('vehicle_id'))
        for item in quote['items']:
            self.add_item_to_sale(sale, item['product_id'], item['quantity'], item['unit_price'])
        sale.notes = f"Converted from quotation {quote['quote_number']}"
        sale._quotation_id = quote_id
        return sale

    def mark_quotation_converted(self, quote_id: int, sale_id: int) -> None:
        changed = self.db.execute_update("UPDATE quotations SET status='CONVERTED', converted_sale_id=?, updated_at=CURRENT_TIMESTAMP WHERE id=? AND status IN ('DRAFT','ISSUED')", (sale_id, quote_id))
        if changed != 1:
            raise ValueError("Quotation was already converted")
        AuditService().log_action('QUOTATION_CONVERTED', 'QUOTATION', quote_id, None, details=f'Sale {sale_id}')

    def change_quotation_status(self, quote_id: int, status: str, user_id: Optional[int] = None) -> dict:
        if status not in ('DRAFT', 'ISSUED', 'CANCELLED', 'EXPIRED'):
            raise ValueError('Invalid quotation status')
        if user_id is not None:
            PermissionService().check_permission_or_raise(user_id, 'quotations.edit')
        if self.db.execute_update("UPDATE quotations SET status=?, issued_at=CASE WHEN ?='ISSUED' THEN CURRENT_TIMESTAMP ELSE issued_at END, updated_at=CURRENT_TIMESTAMP WHERE id=? AND status NOT IN ('CONVERTED','CANCELLED')", (status, status, quote_id)) != 1:
            raise ValueError('Quotation is unavailable for this status change')
        quote = self.get_quotation(quote_id)
        AuditService().log_action(f'QUOTATION_{status}', 'QUOTATION', quote_id, user_id)
        self.sync.enqueue('QUOTATION', quote_id, 'UPDATE', json.dumps(quote))
        self.sync.request_background_sync()
        return quote

    def find_or_create_customer(self, name: str, phone: Optional[str] = None, email: Optional[str] = None,
                                vehicle_make: Optional[str] = None, vehicle_model: Optional[str] = None,
                                vehicle_registration: Optional[str] = None, city: Optional[str] = None) -> int:
        """Find a customer by stable contact details, otherwise create one."""
        name = name.strip()
        phone = (phone or "").strip() or None
        email = (email or "").strip() or None
        if not name:
            raise ValueError("Customer name is required.")
        if phone:
            rows = self.db.execute_query("SELECT id FROM customers WHERE phone = ? ORDER BY id LIMIT 1", (phone,))
            if rows:
                cid = rows[0]["id"]
                self.db.execute_update("UPDATE customers SET name=?, email=?, city=?, vehicle_make=?, vehicle_model=?, vehicle_registration=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                                      (name, email, city, vehicle_make, vehicle_model, vehicle_registration, cid))
                return cid
        if email:
            rows = self.db.execute_query("SELECT id FROM customers WHERE lower(email) = lower(?) ORDER BY id LIMIT 1", (email,))
            if rows:
                return int(rows[0]["id"])
        if not phone and not email:
            rows = self.db.execute_query(
                "SELECT id FROM customers WHERE lower(name) = lower(?) AND COALESCE(vehicle_make, '') = COALESCE(?, '') AND COALESCE(vehicle_model, '') = COALESCE(?, '') AND COALESCE(city, '') = '' ORDER BY id LIMIT 1",
                (name, vehicle_make, vehicle_model),
            )
            if rows:
                return int(rows[0]["id"])
        self.db.execute_update("INSERT INTO customers (name, phone, email, city, vehicle_make, vehicle_model, vehicle_registration) VALUES (?, ?, ?, ?, ?, ?, ?)",
                               (name, phone, email, city, vehicle_make, vehicle_model, vehicle_registration))
        customer_id = self.db.get_last_insert_id()
        customer = self.get_customer(customer_id)
        if customer:
            self.sync.enqueue("CUSTOMER", customer_id, "CREATE", json.dumps(customer.to_dict()))
            self.sync.request_background_sync()
        return customer_id

    def update_customer(self, customer_id: int, name: str, phone: Optional[str] = None,
                        email: Optional[str] = None, city: Optional[str] = None,
                        vehicle_make: Optional[str] = None, vehicle_model: Optional[str] = None,
                        vehicle_registration: Optional[str] = None) -> bool:
        if not name.strip():
            raise ValueError("Customer name is required.")
        changed = self.db.execute_update(
            "UPDATE customers SET name=?, phone=?, email=?, city=?, vehicle_make=?, vehicle_model=?, vehicle_registration=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (name.strip(), phone, email, city, vehicle_make, vehicle_model, vehicle_registration, customer_id),
        )
        if changed:
            customer = self.get_customer(customer_id)
            if customer:
                self.sync.enqueue("CUSTOMER", customer_id, "UPDATE", json.dumps(customer.to_dict()))
                self.sync.request_background_sync()
        return changed == 1

    def _find_or_create_customer_tx(self, conn, name: str, phone: Optional[str] = None, email: Optional[str] = None,
                                    vehicle_make: Optional[str] = None, vehicle_model: Optional[str] = None,
                                    vehicle_registration: Optional[str] = None, city: Optional[str] = None) -> int:
        """Transaction-safe find or create customer using the provided DB connection.
        Uses the same heuristics as find_or_create_customer but executes on the given connection so the caller can include it in a larger transaction.
        """
        name = (name or "").strip()
        phone = (phone or "").strip() or None
        email = (email or "").strip() or None
        if not name:
            raise ValueError("Customer name is required.")
        # Try phone first
        if phone:
            row = conn.execute("SELECT id FROM customers WHERE phone = ? ORDER BY id LIMIT 1", (phone,)).fetchone()
            if row:
                cid = row["id"] if "id" in row.keys() else row[0]
                conn.execute("UPDATE customers SET name=?, email=?, city=?, vehicle_make=?, vehicle_model=?, vehicle_registration=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                             (name, email, city, vehicle_make, vehicle_model, vehicle_registration, cid))
                return cid
        # Then email
        if email:
            row = conn.execute("SELECT id FROM customers WHERE lower(email) = lower(?) ORDER BY id LIMIT 1", (email,)).fetchone()
            if row:
                return int(row["id"] if "id" in row.keys() else row[0])
        # Fallback: match by name+vehicle when no phone/email provided
        if not phone and not email:
            row = conn.execute(
                "SELECT id FROM customers WHERE lower(name) = lower(?) AND COALESCE(vehicle_make, '') = COALESCE(?, '') AND COALESCE(vehicle_model, '') = COALESCE(?, '') AND COALESCE(city, '') = '' ORDER BY id LIMIT 1",
                (name, vehicle_make, vehicle_model),
            ).fetchone()
            if row:
                return int(row["id"] if "id" in row.keys() else row[0])
        # Create new customer
        conn.execute("INSERT INTO customers (name, phone, email, city, vehicle_make, vehicle_model, vehicle_registration) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (name, phone, email, city, vehicle_make, vehicle_model, vehicle_registration))
        last = conn.execute("SELECT last_insert_rowid() as id").fetchone()
        customer_id = int(last["id"] if "id" in last.keys() else last[0])
        return customer_id

    def get_customer(self, customer_id: int):
        from models.customer import Customer
        rows = self.db.execute_query("SELECT * FROM customers WHERE id=?", (customer_id,))
        if not rows:
            return None
        row = rows[0]
        return Customer(**{field: row[field] for field in Customer.__dataclass_fields__ if field in row.keys()})

    def search_customers(self, term: str = ""):
        pattern = f"%{term.strip()}%"
        return self.db.execute_query("SELECT * FROM customers WHERE name LIKE ? OR phone LIKE ? OR email LIKE ? OR city LIKE ? OR vehicle_registration LIKE ? ORDER BY name LIMIT 30",
                         (pattern, pattern, pattern, pattern, pattern))

    def get_sale_by_id(self, sale_id: int) -> Optional[Sale]:
        """Get sale by ID."""
        query = """
            SELECT * FROM sales WHERE id = ?
        """
        
        results = self.db.execute_query(query, (sale_id,))
        if not results:
            return None
        
        return self._load_sale_items(self._row_to_sale(results[0]))

    def get_sale_by_invoice_number(self, invoice_number: str) -> Optional[Sale]:
        """Get sale by invoice number."""
        query = """
            SELECT * FROM sales WHERE invoice_number = ?
        """
        
        results = self.db.execute_query(query, (invoice_number,))
        if not results:
            return None
        
        return self._load_sale_items(self._row_to_sale(results[0]))

    def get_recent_sales(self, limit: int = 20) -> List[Sale]:
        """Get recent sales."""
        query = """
            SELECT * FROM sales 
            ORDER BY created_at DESC 
            LIMIT ?
        """
        
        results = self.db.execute_query(query, (limit,))
        return [self._load_sale_items(self._row_to_sale(row)) for row in results]

    def _load_sale_items(self, sale: Sale) -> Sale:
        """Populate a sale with its persisted line items."""
        rows = self.db.execute_query(
            "SELECT si.*, p.description product_name, p.barcode product_barcode, p.part_no, p.brand, "
            "p.vehicle_make, p.vehicle_model FROM sale_items si "
            "LEFT JOIN products p ON p.id = si.product_id WHERE si.sale_id = ? ORDER BY si.id", (sale.id,)
        )
        sale.items = [
            SaleItem(
                id=row['id'], sale_id=row['sale_id'], product_id=row['product_id'],
                product_name=row['product_name'] or '', product_barcode=row['product_barcode'],
                part_no=row['part_no'] or '', brand=row['brand'] or '',
                vehicle_make=row['vehicle_make'], vehicle_model=row['vehicle_model'],
                quantity=row['quantity'], unit_price=row['unit_price'],
                vat_rate=row['vat_rate'], line_total=row['line_total'],
            )
            for row in rows
        ]
        return sale

    def search_sales(self, search_term: str) -> List[Sale]:
        """Search sales by invoice number or customer name."""
        query = """
            SELECT * FROM sales 
            WHERE invoice_number LIKE ? OR customer_name LIKE ? OR customer_phone LIKE ?
            ORDER BY created_at DESC
        """
        
        pattern = f"%{search_term}%"
        results = self.db.execute_query(query, (pattern, pattern, pattern))
        return [self._row_to_sale(row) for row in results]

    def void_sale(self, sale_id: int, user_id: Optional[int] = None, reason: Optional[str] = None) -> bool:
        """
        Void a sale (and reverse all stock movements).
        
        Args:
            sale_id: Sale ID
            
        Returns:
            True if successful
        """
        sale = self.get_sale_by_id(sale_id)
        if not sale:
            raise ValueError(f"Sale not found: {sale_id}")
        actor_id = user_id if user_id is not None else sale.user_id
        PermissionService().check_permission_or_raise(actor_id, 'VOID_SALE')
        if sale.status == 'VOIDED':
            raise ValueError(f"Sale already voided: {sale_id}")
        try:
            with self.db.transaction() as conn:
                updated = conn.execute(
                    "UPDATE sales SET status = 'VOIDED', updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status != 'VOIDED'",
                    (sale_id,),
                ).rowcount
                if updated != 1:
                    raise ValueError(f"Sale already voided: {sale_id}")
                for item in sale.items:
                    product = conn.execute(
                        "SELECT quantity_on_hand FROM products WHERE id = ?", (item.product_id,)
                    ).fetchone()
                    if product is None:
                        raise ValueError(f"Product not found: {item.product_id}")
                    previous = product[0]
                    new_quantity = previous + item.quantity
                    conn.execute(
                        "UPDATE products SET quantity_on_hand = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (new_quantity, item.product_id),
                    )
                    conn.execute(
                        "INSERT INTO stock_movements (product_id, movement_type, quantity, previous_quantity, new_quantity, reference, user_id, notes) VALUES (?, 'VOID', ?, ?, ?, ?, ?, ?)",
                        (item.product_id, item.quantity, previous, new_quantity, sale.invoice_number, actor_id, f"Voided sale {sale.invoice_number}"),
                    )
                conn.execute(
                    "INSERT INTO audit_logs (action, entity_type, entity_id, requesting_user_id, reason, details, status) VALUES (?, ?, ?, ?, ?, ?, 'COMPLETED')",
                    ('SALE_VOIDED', 'SALE', sale_id, actor_id, reason, f"Invoice: {sale.invoice_number}"),
                )
            self.sync.enqueue("SALE", sale_id, "UPDATE", json.dumps({"id": sale_id, "status": "VOIDED", "invoice_number": sale.invoice_number}))
            self.sync.request_background_sync()
            logger.info(f"Sale voided: {sale.invoice_number}")
            return True
        except Exception as e:
            logger.error(f"Failed to void sale: {e}")
            raise

    def void_invoice(self, invoice_number: str, user_id: int, reason: str = "") -> bool:
        """Void a paid invoice without deleting its sale, payments, or audit trail."""
        permissions = PermissionService()
        if not permissions.is_admin(user_id) or not permissions.has_permission(user_id, 'VOID_SALE'):
            raise PermissionError('Only an authorized administrator can void invoices')
        rows = self.db.execute_query('SELECT id,sale_id,status FROM invoices WHERE invoice_number=?', (invoice_number,))
        if not rows:
            raise ValueError('Invoice was not found')
        invoice = rows[0]
        if invoice['status'] == 'VOIDED':
            raise ValueError('Invoice is already voided')
        if invoice['status'] == 'DRAFT':
            raise ValueError('Draft invoices must be deleted, not voided')
        self.void_sale(invoice['sale_id'], user_id, reason or 'Invoice voided')
        if self.db.execute_update("UPDATE invoices SET status='VOIDED',voided_by=?,voided_at=CURRENT_TIMESTAMP,void_reason=? WHERE id=? AND status!='VOIDED'", (user_id, reason or None, invoice['id'])) != 1:
            raise ValueError('Invoice could not be voided')
        AuditService().log_action('INVOICE_VOIDED', 'INVOICE', invoice['id'], user_id, reason or None, f'Invoice: {invoice_number}')
        return True

    def delete_draft_invoice(self, invoice_number: str, user_id: int) -> bool:
        """Delete only an unissued draft invoice; paid/completed invoices are immutable."""
        PermissionService().check_permission_or_raise(user_id, 'invoices.view')
        rows = self.db.execute_query('SELECT id,status FROM invoices WHERE invoice_number=?', (invoice_number,))
        if not rows:
            raise ValueError('Invoice was not found')
        if rows[0]['status'] != 'DRAFT':
            raise ValueError('Only draft invoices can be deleted; void a completed invoice instead')
        if self.db.execute_update("DELETE FROM invoices WHERE id=? AND status='DRAFT'", (rows[0]['id'],)) != 1:
            raise ValueError('Draft invoice could not be deleted')
        AuditService().log_action('INVOICE_DRAFT_DELETED', 'INVOICE', rows[0]['id'], user_id, details=f'Invoice: {invoice_number}')
        return True

    @staticmethod
    def _generate_invoice_number() -> str:
        """Generate a unique invoice number."""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        unique_id = str(uuid.uuid4())[:8].upper()
        return f"INV-{timestamp}-{unique_id}"

    @staticmethod
    def _row_to_sale(row) -> Sale:
        """Convert database row to Sale object."""
        sale = Sale(
            id=row['id'],
            invoice_number=row['invoice_number'],
            customer_id=row['customer_id'],
            customer_name=row['customer_name'],
            customer_phone=row['customer_phone'],
            customer_email=row['customer_email'] if 'customer_email' in row.keys() else None,
            customer_city=row['customer_city'] if 'customer_city' in row.keys() else None,
            vehicle_id=row['vehicle_id'] if 'vehicle_id' in row.keys() else None,
            vehicle_make=row['vehicle_make'] if 'vehicle_make' in row.keys() else None,
            vehicle_model=row['vehicle_model'] if 'vehicle_model' in row.keys() else None,
            vehicle_registration=row['vehicle_registration'] if 'vehicle_registration' in row.keys() else None,
            user_id=row['user_id'],
            cashier_name=row['cashier_name'] if 'cashier_name' in row.keys() else '',
            subtotal=row['subtotal'],
            vat_amount=row['vat_amount'],
            discount_amount=row['discount_amount'],
            total=row['total'],
            status=row['status'],
            notes=row['notes'],
            created_at=datetime.fromisoformat(row['created_at']) if row['created_at'] else None,
            updated_at=datetime.fromisoformat(row['updated_at']) if row['updated_at'] else None,
        )
        
        return sale
