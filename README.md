# Motor Spares POS - Offline-First Inventory Management System

A production-ready, offline-first Point of Sale and Inventory Management System for motor spares shops in Zimbabwe.

## Current Status: PHASE 2 ✅ COMPLETE

### PHASE 1 Features (Implemented)
- ✅ SQLite database with normalized schema
- ✅ Product management (Create, Read, Search, Update)
- ✅ Stock/Inventory tracking with movement history
- ✅ Low stock and out-of-stock monitoring
- ✅ Barcode support (via unique barcode field)
- ✅ Vehicle-specific product lookup (Toyota, Honda, etc.)
- ✅ Categories system
- ✅ Basic test window with inventory dashboard

### Project Structure

```
motor_spares_pos/
├── main.py                      # Entry point
├── config.json                  # Configuration
├── requirements.txt             # Python dependencies
│
├── database/
│   ├── __init__.py
│   ├── db.py                   # Database connection and initialization
│   └── schema.py               # SQLite schema definition
│
├── models/
│   ├── __init__.py
│   └── product.py              # Product, Category, VehicleModel, StockMovement dataclasses
│
├── services/
│   ├── __init__.py
│   ├── product_service.py      # Product CRUD operations
│   └── inventory_service.py    # Stock movements and inventory tracking
│
├── ui/
│   ├── __init__.py
│   └── test_window.py          # Basic PySide6 test window
│
├── printers/
│   ├── __init__.py
│   └── receipt_printer.py      # (Coming in PHASE 4)
│
├── fiscal/
│   ├── __init__.py
│   ├── fiscal_driver.py        # (Coming in PHASE 8)
│   └── mock_fiscal_device.py   # (Coming in PHASE 8)
│
├── sync/
│   ├── __init__.py
│   ├── sync_manager.py         # (Coming in PHASE 5)
│   ├── connection_monitor.py   # (Coming in PHASE 5)
│   └── conflict_manager.py     # (Coming in PHASE 5)
│
├── reports/
│   ├── __init__.py
│   └── report_generator.py     # (Coming in PHASE 6)
│
├── data/
│   └── pos.db                  # SQLite database (auto-created)
│
└── assets/
    └── logo/                   # Company logo placeholder
```

## Installation & Setup

### Prerequisites
- Python 3.10 or higher
- Windows 10/11
- pip (Python package manager)

### Installation Steps - Core Only (PHASE 1)

For PHASE 1 testing with command-line interface:

```bash
# 1. Navigate to project directory
cd "c:\Users\HomePC\Documents\Online Motor Spare Pos System"

# 2. Create virtual environment (recommended)
python -m venv venv

# 3. Activate virtual environment
venv\Scripts\activate

# 4. Install core dependencies (no GUI yet)
pip install -r requirements-core.txt
```

### Full Installation (All Phases - Optional)

For the complete system with GUI (PySide6 is large, ~500MB download):

```bash
pip install -r requirements.txt
```

## Running the Application

### PHASE 1 Command-Line Test Suite (No GUI Required)

```bash
cd "c:\Users\HomePC\Documents\Online Motor Spare Pos System"
python motor_spares_pos/test_phase1.py
```

This runs comprehensive tests for:
- ✓ Database initialization and schema
- ✓ Product CRUD operations (Create, Read, Search, Update)
- ✓ Stock level monitoring
- ✓ Stock movement recording and history
- ✓ Inventory summaries

**Expected Output:**
```
████████████████████████████████ Motor Spares POS - PHASE 1 Test Suite ████████████████████████████████
✓ PASS  -  Database
✓ PASS  -  Products
✓ PASS  -  StockLevels
✓ PASS  -  Movements

Total: 4/4 tests passed
🎉 All tests passed! PHASE 1 is working correctly.
```

### PHASE 1 GUI Test Window (Requires Full Installation)

After installing `requirements.txt`:

```bash
cd "c:\Users\HomePC\Documents\Online Motor Spare Pos System"
python motor_spares_pos/main.py
```

This launches the test window with sample data showing:
- Inventory summary dashboard
- Product search and listing
- Low stock/out of stock alerts
- Stock movement testing interface

## PHASE 1 Testing Checklist

### Test the following:

#### 1. **Database Initialization**
- [ ] Application starts without errors
- [ ] `motor_spares_pos/data/pos.db` is created
- [ ] Database tables are created (categories, products, stock_movements, etc.)

#### 2. **Sample Data**
- [ ] "Inventory Summary" tab shows:
  - Total Products: 8
  - In Stock: 7
  - Out of Stock: 1 (Honda Civic Oil Filter)
  - Low Stock: 1 (Toyota Corolla Fan Belt - stock 3, reorder 5)
  - Total Units: 88
  - Inventory Value: calculated correctly

#### 3. **Products Tab**
- [ ] Click "Show All" - displays all 8 products
- [ ] Search "Toyota" - shows 5 Toyota products
- [ ] Search "Brake" - shows brake pad products
- [ ] Search "Bosch" - shows Bosch brand products
- [ ] Search by barcode (e.g., "8711111111111") - finds product
- [ ] Out-of-stock products highlighted in red
- [ ] Low-stock products highlighted in yellow

#### 4. **Low Stock Tab**
- [ ] "Refresh Low Stock List" shows 2 products:
  - Honda Civic Oil Filter (0 stock)
  - Toyota Corolla Fan Belt (3 stock)

#### 5. **Test Operations Tab**
- [ ] Select a product from dropdown
- [ ] Record a SALE movement (e.g., sell 2 units)
  - Stock should decrease
  - Inventory summary should update
  - Status should show movement recorded
- [ ] Record a PURCHASE movement
  - Stock should increase
- [ ] Record a RETURN movement
- [ ] View movement history - shows all movements in order

#### 6. **Stock Movement Validation**
- [ ] Cannot sell more than available stock (should error)
- [ ] Can record PURCHASE to increase stock
- [ ] Each movement creates an audit trail
- [ ] Stock level updates immediately

#### 7. **Performance**
- [ ] Product search is fast
- [ ] Summary refreshes quickly
- [ ] No lag when viewing history

#### 8. **Data Persistence**
- [ ] Close and reopen application
- [ ] All previously created data is still there
- [ ] Stock movements are preserved
- [ ] Changes persist to pos.db

## Technology Stack

### Core Technologies
- **Python 3.10+**: Programming language
- **PySide6**: Desktop GUI framework
- **SQLite**: Local offline database

### Libraries
- `pandas`: Data analysis and Excel operations
- `openpyxl`: Excel file handling
- `pyserial`: Hardware communication (barcode scanners)
- `python-escpos`: Thermal receipt printer control
- `reportlab`: PDF generation
- `Pillow`: Image handling
- `requests`: HTTP client for synchronization
- `bcrypt`: Password hashing

## Database Schema - PHASE 1

### Tables Created

#### categories
- id (PRIMARY KEY)
- name (UNIQUE)
- description
- created_at, updated_at

#### vehicle_models
- id (PRIMARY KEY)
- make
- model
- year_from, year_to
- created_at

#### products
- id (PRIMARY KEY)
- barcode (UNIQUE, nullable)
- part_no (UNIQUE)
- description
- brand
- category_id (FK)
- vehicle_make, vehicle_model
- cost_price, selling_price
- currency (default: ZWL)
- quantity_on_hand
- reorder_level
- vat_rate (default: 15%)
- active (default: 1)
- created_at, updated_at

#### stock_movements
- id (PRIMARY KEY)
- product_id (FK)
- movement_type (PURCHASE, SALE, RETURN, ADJUSTMENT, DAMAGE, TRANSFER, VOID)
- quantity
- previous_quantity, new_quantity
- reference (e.g., invoice number)
- user_id (FK, for future use)
- notes
- created_at

#### settings
- id (PRIMARY KEY)
- key (UNIQUE)
- value
- data_type
- created_at, updated_at

### Indexes
- idx_products_barcode
- idx_products_part_no
- idx_products_category
- idx_products_vehicle
- idx_stock_movements_product
- idx_stock_movements_date

## API Usage Examples

### Product Service

```python
from services.product_service import ProductService
from models.product import Product

service = ProductService()

# Create a product
product = Product(
    barcode='8711111111111',
    part_no='BP04465',
    description='Brake Pads Front',
    brand='Bosch',
    cost_price=15.00,
    selling_price=35.00,
    quantity_on_hand=10,
    reorder_level=5,
)
product_id = service.create_product(product)

# Search products
results = service.search_products('Toyota')

# Get low stock products
low_stock = service.get_low_stock_products()

# Get inventory summary
summary = service.get_inventory_summary()
# Returns: {
#   'total_products': 8,
#   'in_stock': 7,
#   'out_of_stock': 1,
#   'low_stock': 1,
#   'total_units': 88,
#   'inventory_value': 450.50
# }
```

### Inventory Service

```python
from services.inventory_service import InventoryService

service = InventoryService()

# Record a sale
movement_id = service.sell_product(
    product_id=1,
    quantity=2,
    invoice_number='INV-000001',
    user_id=1
)

# Record stock receipt
movement_id = service.receive_stock(
    product_id=1,
    quantity=50,
    po_number='PO-12345',
    user_id=1
)

# Get movement history
history = service.get_product_movement_history(product_id=1, limit=20)

# Adjust stock
service.adjust_stock(
    product_id=1,
    quantity_change=-2,
    reason='Inventory correction',
    user_id=1
)
```

## PHASE 2 Status

Implemented and verified:

- User authentication and role-based access control
- Sales, invoices, returns, and refunds
- Offline sync queue with idempotent processing
- Audit logging for sensitive actions

Next, PHASE 3 can add the dedicated POS and administration screens.

## Notes

- **Offline-First**: All data is stored locally in SQLite. Internet connection is NOT required.
- **Synchronization**: Designed for future sync with server (PHASE 5)
- **No Fiscal Device Hardcoding**: Mock fiscal device interface (PHASE 8) allows plugging in real drivers when documentation is available.
- **Zimbabwe-Ready**: Support for ZWL and USD currencies with configurable exchange rates.

## Support

For issues or questions during testing, please check:
1. The console output for error messages
2. The database file at `motor_spares_pos/data/pos.db`
3. Application logs in the terminal

---

**Project Version**: 1.1.0 - PHASE 2 Complete
**Last Updated**: 2026-09-01
